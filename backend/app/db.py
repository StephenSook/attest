"""SQLite access. WAL mode, single writer, durable when its path is persistent."""

import fcntl
import os
import sqlite3
import time
from pathlib import Path

_PRAGMAS = (
    "PRAGMA busy_timeout=5000",
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS call_runs (
    run_id TEXT PRIMARY KEY,
    calle_call_id TEXT UNIQUE,
    idempotency_key TEXT UNIQUE NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    terminal_payload TEXT,
    record_json TEXT,
    dispatch_digest TEXT,
    dispatch_base_url TEXT,
    dispatch_provider TEXT,
    dispatch_credential_fingerprint TEXT,
    destination_hash TEXT,
    dispatch_expires_at REAL,
    submit_attempts INTEGER NOT NULL DEFAULT 0,
    submit_lease_owner TEXT,
    submit_lease_until REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sandbox_reservations (
    phone_hash TEXT PRIMARY KEY,
    reserved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS runtime_bindings (
    name TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS call_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES call_runs(run_id),
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (run_id, seq)
);
"""


def db_path() -> Path:
    return Path(os.environ.get("ATTEST_DB_PATH", "./data/attest.db"))


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=30.0)
    conn.row_factory = sqlite3.Row
    migrations = {
        "dispatch_digest": "ALTER TABLE call_runs ADD COLUMN dispatch_digest TEXT",
        "dispatch_base_url": "ALTER TABLE call_runs ADD COLUMN dispatch_base_url TEXT",
        "dispatch_provider": "ALTER TABLE call_runs ADD COLUMN dispatch_provider TEXT",
        "dispatch_credential_fingerprint": (
            "ALTER TABLE call_runs ADD COLUMN dispatch_credential_fingerprint TEXT"
        ),
        "destination_hash": "ALTER TABLE call_runs ADD COLUMN destination_hash TEXT",
        "dispatch_expires_at": "ALTER TABLE call_runs ADD COLUMN dispatch_expires_at REAL",
        "submit_attempts": (
            "ALTER TABLE call_runs ADD COLUMN submit_attempts INTEGER NOT NULL DEFAULT 0"
        ),
        "submit_lease_owner": "ALTER TABLE call_runs ADD COLUMN submit_lease_owner TEXT",
        "submit_lease_until": (
            "ALTER TABLE call_runs ADD COLUMN submit_lease_until REAL NOT NULL DEFAULT 0"
        ),
    }
    try:
        # journal_mode changes can return SQLITE_BUSY before busy_timeout is
        # effective. Serialize the complete initialization across processes,
        # then keep the ALTER inspection under SQLite's own write lock too.
        # Closing the sidecar releases flock even if startup raises.
        lock_path = target.with_name(f"{target.name}.init.lock")
        with lock_path.open("a+b") as init_lock:
            fcntl.flock(init_lock.fileno(), fcntl.LOCK_EX)
            for pragma in _PRAGMAS:
                conn.execute(pragma)
            conn.executescript(_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(call_runs)")}
            for name, statement in migrations.items():
                if name not in columns:
                    conn.execute(statement)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_call_runs_destination_hash "
                "ON call_runs(destination_hash)"
            )
            conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
        raise
    return conn


def create_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    idempotency_key: str,
    record_json: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO call_runs (run_id, idempotency_key, state, record_json) "
        "VALUES (?, ?, 'created', ?)",
        (run_id, idempotency_key, record_json),
    )
    conn.commit()


def list_runs(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT run_id, state, created_at, updated_at, record_json, terminal_payload "
            "FROM call_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    )


def list_published_runs(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    """Return only explicitly published rows, applying the limit afterward."""
    return list(
        conn.execute(
            "SELECT run_id, state, created_at, updated_at, record_json, terminal_payload "
            "FROM call_runs WHERE json_valid(record_json) = 1 "
            "AND json_extract(record_json, '$.published') = 1 "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    )


def bind_runtime_fingerprint(
    conn: sqlite3.Connection,
    *,
    name: str,
    fingerprint: str,
) -> str:
    """Bind a stable runtime identity before it protects persisted hashes.

    Returns bound for the first clean database, match for the same identity,
    mismatch after rotation, or unbound_data for a legacy database whose
    existing destination hashes cannot be attributed safely.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT fingerprint FROM runtime_bindings WHERE name = ?",
            (name,),
        ).fetchone()
        if row is not None:
            outcome = "match" if str(row["fingerprint"]) == fingerprint else "mismatch"
            conn.execute("COMMIT")
            return outcome
        has_protected_data = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM sandbox_reservations) OR "
            "EXISTS(SELECT 1 FROM call_runs WHERE destination_hash IS NOT NULL)"
        ).fetchone()[0]
        if has_protected_data:
            conn.execute("ROLLBACK")
            return "unbound_data"
        conn.execute(
            "INSERT INTO runtime_bindings (name, fingerprint) VALUES (?, ?)",
            (name, fingerprint),
        )
        conn.execute("COMMIT")
        return "bound"
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def update_run_record(conn: sqlite3.Connection, run_id: str, record_json: str) -> None:
    conn.execute(
        "UPDATE call_runs SET record_json = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE run_id = ?",
        (record_json, run_id),
    )
    conn.commit()


def update_run_record_metadata(conn: sqlite3.Connection, run_id: str, record_json: str) -> None:
    """Replace record metadata without changing the run lifecycle timestamp."""
    conn.execute(
        "UPDATE call_runs SET record_json = ? WHERE run_id = ?",
        (record_json, run_id),
    )
    conn.commit()


def set_submit_error(conn: sqlite3.Connection, run_id: str, error_json: str) -> bool:
    """Record an ambiguous submit only while no accepted call is known.

    Returns False when another worker has already accepted or completed the
    call. A late timeout must never replace authoritative terminal evidence.
    """
    cursor = conn.execute(
        "UPDATE call_runs SET terminal_payload = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE run_id = ? AND state = 'created' "
        "AND (calle_call_id IS NULL OR calle_call_id = '')",
        (error_json, run_id),
    )
    conn.commit()
    return cursor.rowcount == 1


def claim_submission_attempt(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    dispatch_digest: str,
    dispatch_base_url: str,
    dispatch_provider: str,
    dispatch_credential_fingerprint: str,
    destination_hash: str,
    lease_owner: str,
    now: float | None = None,
    lease_seconds: float = 120.0,
    recovery_window_seconds: float = 600.0,
) -> tuple[str, int]:
    """Claim one external submission attempt without storing its raw request.

    The database keeps only a request digest, an attempt counter, and an
    owner-token lease. A retry cannot change the task, destination, provider,
    or endpoint bound to the idempotency key. Returns an outcome and the
    attempt number: claimed, busy, closed, expired, or mismatch.
    """
    current = time.time() if now is None else now
    expired_payload = (
        '{"error":"dispatch recovery window expired","stage":"submit_recovery_expired"}'
    )
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT state, calle_call_id, dispatch_digest, dispatch_base_url, "
            "dispatch_provider, dispatch_credential_fingerprint, destination_hash, "
            "dispatch_expires_at, "
            "submit_attempts, submit_lease_owner, submit_lease_until "
            "FROM call_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"unknown run {run_id}")
        attempts = int(row["submit_attempts"] or 0)
        if row["state"] != "created" or row["calle_call_id"]:
            conn.execute(
                "UPDATE call_runs SET submit_lease_owner = NULL, submit_lease_until = 0 "
                "WHERE run_id = ?",
                (run_id,),
            )
            conn.execute("COMMIT")
            return "closed", attempts
        stored_digest = str(row["dispatch_digest"] or "")
        if stored_digest and stored_digest != dispatch_digest:
            conn.execute("ROLLBACK")
            return "mismatch", attempts
        persisted_identity = {
            "dispatch_base_url": dispatch_base_url,
            "dispatch_provider": dispatch_provider,
            "dispatch_credential_fingerprint": dispatch_credential_fingerprint,
            "destination_hash": destination_hash,
        }
        for column, current_value in persisted_identity.items():
            stored_value = str(row[column] or "")
            if stored_value and stored_value != current_value:
                conn.execute("ROLLBACK")
                return "mismatch", attempts
        expires_at = (
            float(row["dispatch_expires_at"])
            if row["dispatch_expires_at"] is not None
            else current + recovery_window_seconds
        )
        active_owner = str(row["submit_lease_owner"] or "")
        lease_until = float(row["submit_lease_until"] or 0)
        if expires_at <= current:
            if lease_until > current and active_owner != lease_owner:
                conn.execute("ROLLBACK")
                return "busy", attempts
            conn.execute(
                "UPDATE call_runs SET state = 'failed', terminal_payload = ?, "
                "submit_lease_owner = NULL, submit_lease_until = 0, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE run_id = ? AND state = 'created'",
                (expired_payload, run_id),
            )
            conn.execute("COMMIT")
            return "expired", attempts
        if lease_until > current and active_owner != lease_owner:
            conn.execute("ROLLBACK")
            return "busy", attempts
        attempt_number = attempts + 1
        conn.execute(
            "UPDATE call_runs SET dispatch_digest = ?, dispatch_base_url = ?, "
            "dispatch_provider = ?, dispatch_credential_fingerprint = ?, "
            "destination_hash = ?, dispatch_expires_at = ?, "
            "submit_attempts = ?, submit_lease_owner = ?, submit_lease_until = ? "
            "WHERE run_id = ? AND state = 'created'",
            (
                dispatch_digest,
                dispatch_base_url,
                dispatch_provider,
                dispatch_credential_fingerprint,
                destination_hash,
                expires_at,
                attempt_number,
                lease_owner,
                current + lease_seconds,
                run_id,
            ),
        )
        conn.execute("COMMIT")
        return "claimed", attempt_number
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def release_submission_lease(
    conn: sqlite3.Connection,
    run_id: str,
    lease_owner: str,
) -> bool:
    """Release only the lease owned by this submission attempt."""
    cursor = conn.execute(
        "UPDATE call_runs SET submit_lease_owner = NULL, submit_lease_until = 0 "
        "WHERE run_id = ? AND submit_lease_owner = ?",
        (run_id, lease_owner),
    )
    conn.commit()
    return cursor.rowcount == 1


def expire_submission_attempts(conn: sqlite3.Connection, *, now: float | None = None) -> int:
    """Fail expired, unleased unknown outcomes without permitting a late dial."""
    current = time.time() if now is None else now
    payload = '{"error":"dispatch recovery window expired","stage":"submit_recovery_expired"}'
    cursor = conn.execute(
        "UPDATE call_runs SET state = 'failed', terminal_payload = ?, "
        "submit_lease_owner = NULL, submit_lease_until = 0, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE state = 'created' AND (calle_call_id IS NULL OR calle_call_id = '') "
        "AND dispatch_expires_at IS NOT NULL AND dispatch_expires_at <= ? "
        "AND submit_lease_until <= ?",
        (payload, current, current),
    )
    conn.commit()
    return cursor.rowcount


def clear_submit_error(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute(
        "UPDATE call_runs SET terminal_payload = NULL, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE run_id = ?",
        (run_id,),
    )
    conn.commit()


def set_calle_call_id(conn: sqlite3.Connection, run_id: str, calle_call_id: str) -> None:
    conn.execute(
        "UPDATE call_runs SET calle_call_id = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE run_id = ?",
        (calle_call_id, run_id),
    )
    conn.commit()


def accept_submission(conn: sqlite3.Connection, run_id: str, calle_call_id: str) -> bool:
    """Atomically record provider acceptance and enter the submitted state.

    Returns True when a created run is promoted and False when the same
    accepted call was already persisted. The call id, cleared submit error,
    and lifecycle transition must never be split across commits.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT state, calle_call_id FROM call_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError(f"unknown run {run_id}")
        state = str(row["state"])
        existing_call_id = str(row["calle_call_id"] or "")
        if state == "created":
            cursor = conn.execute(
                "UPDATE call_runs SET calle_call_id = ?, state = 'submitted', "
                "terminal_payload = NULL, submit_lease_owner = NULL, "
                "submit_lease_until = 0, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE run_id = ? AND state = 'created'",
                (calle_call_id, run_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"run {run_id} changed during submission acceptance")
            conn.execute("COMMIT")
            return True
        if existing_call_id == calle_call_id and state in {
            "submitted",
            "completed",
            "failed",
            "canceled",
        }:
            conn.execute(
                "UPDATE call_runs SET submit_lease_owner = NULL, submit_lease_until = 0 "
                "WHERE run_id = ?",
                (run_id,),
            )
            conn.execute("COMMIT")
            return False
        raise RuntimeError(f"run {run_id} cannot accept provider call {calle_call_id}")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def reject_submission(
    conn: sqlite3.Connection,
    run_id: str,
    error_json: str,
    *,
    lease_owner: str,
    attempt_number: int,
    sandbox_phone_hash: str | None = None,
) -> bool:
    """Atomically fail a definitely rejected submit and return its sandbox slot."""
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE call_runs SET state = 'failed', terminal_payload = ?, "
            "submit_lease_owner = NULL, submit_lease_until = 0, "
            "destination_hash = NULL, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
            "WHERE run_id = ? AND state = 'created' "
            "AND submit_lease_owner = ? AND submit_attempts = ?",
            (error_json, run_id, lease_owner, attempt_number),
        )
        if cursor.rowcount != 1:
            conn.execute("ROLLBACK")
            return False
        if sandbox_phone_hash is not None:
            conn.execute(
                "DELETE FROM sandbox_reservations WHERE phone_hash = ?",
                (sandbox_phone_hash,),
            )
        conn.execute("COMMIT")
        return True
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def get_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM call_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    return row


def get_run_by_calle_call_id(conn: sqlite3.Connection, calle_call_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM call_runs WHERE calle_call_id = ?", (calle_call_id,)
    ).fetchone()
    return row


def pollable_runs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Non-terminal runs that CALL-E knows about. What the poller resumes from.

    Includes created-state runs that already hold a call id: a crash between
    submit and the submitted transition must not orphan a run whose phone
    actually rang.
    """
    return list(
        conn.execute(
            "SELECT * FROM call_runs WHERE state IN ('submitted', 'created') "
            "AND calle_call_id IS NOT NULL AND calle_call_id != ''"
        )
    )


def reserve_sandbox_slot(conn: sqlite3.Connection, phone_hash: str, cap: int) -> str:
    """Atomically claim one judge-sandbox call slot for a phone hash.

    A single serialized transaction enforces BOTH invariants that used to
    race outside the submission lock: the per-number dedup (PRIMARY KEY on
    phone_hash) and the global cap (count checked inside the same
    transaction, before insert). Correct even across processes because
    SQLite serializes writers. Returns "ok", "duplicate", or "capped"; never
    raises for the expected outcomes.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
        count = conn.execute("SELECT COUNT(*) FROM sandbox_reservations").fetchone()[0]
        if count >= cap:
            conn.execute("ROLLBACK")
            return "capped"
        existing = conn.execute(
            "SELECT 1 FROM sandbox_reservations WHERE phone_hash = ?", (phone_hash,)
        ).fetchone()
        if existing is not None:
            conn.execute("ROLLBACK")
            return "duplicate"
        conn.execute("INSERT INTO sandbox_reservations (phone_hash) VALUES (?)", (phone_hash,))
        conn.execute("COMMIT")
        return "ok"
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        return "duplicate"


def create_sandbox_run(
    conn: sqlite3.Connection,
    *,
    phone_hash: str,
    cap: int,
    run_id: str,
    idempotency_key: str,
    record_json: str,
) -> str:
    """Atomically reserve a judge slot and create its recoverable run row.

    A repeated request id is reported separately so the caller can validate
    its capability and safely resume it. No phone reservation can survive a
    failed run insert.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM call_runs WHERE run_id = ?", (run_id,)).fetchone():
            conn.execute("ROLLBACK")
            return "request_exists"
        count = conn.execute("SELECT COUNT(*) FROM sandbox_reservations").fetchone()[0]
        if count >= cap:
            conn.execute("ROLLBACK")
            return "capped"
        if conn.execute(
            "SELECT 1 FROM sandbox_reservations WHERE phone_hash = ?", (phone_hash,)
        ).fetchone():
            conn.execute("ROLLBACK")
            return "duplicate"
        conn.execute("INSERT INTO sandbox_reservations (phone_hash) VALUES (?)", (phone_hash,))
        conn.execute(
            "INSERT INTO call_runs "
            "(run_id, idempotency_key, state, record_json, destination_hash) "
            "VALUES (?, ?, 'created', ?, ?)",
            (run_id, idempotency_key, record_json, phone_hash),
        )
        conn.execute("COMMIT")
        return "ok"
    except sqlite3.IntegrityError:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        if conn.execute("SELECT 1 FROM call_runs WHERE run_id = ?", (run_id,)).fetchone():
            return "request_exists"
        return "duplicate"
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def create_request_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    idempotency_key: str,
    record_json: str,
    destination_hash: str,
) -> str:
    """Create an operator run without bypassing an ambiguous destination.

    A new request identity may target the same number only when every older
    dispatch has a known provider call id or was definitely rejected. An
    unknown outcome remains blocked after its retry window expires, so losing
    browser storage cannot turn uncertainty into a second call.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM call_runs WHERE run_id = ?", (run_id,)).fetchone():
            conn.execute("ROLLBACK")
            return "request_exists"
        guarded = conn.execute(
            "SELECT 1 FROM call_runs WHERE destination_hash = ? "
            "AND calle_call_id IS NULL "
            "AND state IN ('created', 'failed') LIMIT 1",
            (destination_hash,),
        ).fetchone()
        if guarded is not None:
            conn.execute("ROLLBACK")
            return "destination_blocked"
        conn.execute(
            "INSERT INTO call_runs "
            "(run_id, idempotency_key, state, record_json, destination_hash) "
            "VALUES (?, ?, 'created', ?, ?)",
            (run_id, idempotency_key, record_json, destination_hash),
        )
        conn.execute("COMMIT")
        return "ok"
    except sqlite3.IntegrityError:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        return "request_exists"
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def release_sandbox_slot(conn: sqlite3.Connection, phone_hash: str) -> None:
    """Give a slot back if the call never actually got placed."""
    conn.execute("DELETE FROM sandbox_reservations WHERE phone_hash = ?", (phone_hash,))
    conn.commit()
