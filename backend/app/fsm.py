"""Explicit run state machine. Every allowed transition is declared here.

States:
    created    row exists, nothing sent to CALL-E yet
    submitted  CALL-E accepted the call task (we hold calle_call_id)
    completed / failed / canceled   terminal, payload recorded

The webhook and the poller race by design; terminal writes go through a
single guarded UPDATE so whichever arrives first wins and the loser no-ops.
"""

import sqlite3

TERMINAL_STATES = frozenset({"completed", "failed", "canceled"})

ALLOWED: dict[str, frozenset[str]] = {
    "created": frozenset({"submitted", "failed"}),
    "submitted": TERMINAL_STATES,
}


class TransitionError(Exception):
    pass


def advance(
    conn: sqlite3.Connection,
    run_id: str,
    new_state: str,
    *,
    terminal_payload: str | None = None,
) -> bool:
    """Advance a run. Returns True if the write landed, False on a benign no-op
    (the run already reached a terminal state, e.g. the race loser). Raises
    TransitionError on a genuinely illegal transition or unknown run.
    """
    row = conn.execute("SELECT state FROM call_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise TransitionError(f"unknown run {run_id}")
    current = str(row["state"])

    if current in TERMINAL_STATES:
        return False
    if new_state not in ALLOWED.get(current, frozenset()):
        raise TransitionError(f"illegal transition {current} -> {new_state} for {run_id}")

    cursor = conn.execute(
        """
        UPDATE call_runs
        SET state = ?,
            terminal_payload = COALESCE(?, terminal_payload),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE run_id = ? AND state = ?
        """,
        (new_state, terminal_payload, run_id, current),
    )
    conn.commit()
    return cursor.rowcount == 1
