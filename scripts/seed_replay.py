"""Seed the database with the scrubbed real probe payload as a labeled replay.

Idempotent: running twice is a no-op. This is what public console visitors
see: a replay of a real recorded run, labeled as such, never a live dial.

    uv run python scripts/seed_replay.py
"""

import json
from pathlib import Path

from app import db, fsm

FIXTURE = Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json"
RUN_ID = "run_replay_probe_0001"


def main() -> None:
    payload = json.loads(FIXTURE.read_text())
    conn = db.connect(db.db_path())
    try:
        if db.get_run(conn, RUN_ID) is not None:
            print(f"{RUN_ID} already seeded; nothing to do")
            return
        record = {
            "org": "Example Counseling Center",
            "replay": True,
            "claims": {"accepting_new_patients": "yes", "accepts_plan": "yes"},
        }
        db.create_run(
            conn,
            run_id=RUN_ID,
            idempotency_key=RUN_ID,
            record_json=json.dumps(record),
        )
        db.set_calle_call_id(conn, RUN_ID, str(payload["id"]))
        fsm.advance(conn, RUN_ID, "submitted")
        fsm.advance(conn, RUN_ID, "completed", terminal_payload=json.dumps(payload))
        print(f"seeded {RUN_ID} (labeled replay of the scrubbed real probe call)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
