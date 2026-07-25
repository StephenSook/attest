"""SQLite access. WAL mode, single writer, durable across restarts."""

import os
import sqlite3
from pathlib import Path

_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=5000",
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
    record_json TEXT
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
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    conn.executescript(_SCHEMA)
    try:
        conn.execute("ALTER TABLE call_runs ADD COLUMN record_json TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists (fresh schema or prior migration)
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
            "SELECT run_id, state, created_at, updated_at, record_json "
            "FROM call_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    )


def set_calle_call_id(conn: sqlite3.Connection, run_id: str, calle_call_id: str) -> None:
    conn.execute(
        "UPDATE call_runs SET calle_call_id = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE run_id = ?",
        (calle_call_id, run_id),
    )
    conn.commit()


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
    """Non-terminal runs that CALL-E knows about. What the poller resumes from."""
    return list(
        conn.execute(
            "SELECT * FROM call_runs WHERE state = 'submitted' AND calle_call_id IS NOT NULL"
        )
    )
