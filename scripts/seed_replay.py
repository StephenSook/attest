"""Seed the database with the scrubbed real probe payload as a labeled replay.

Idempotent: running twice is a no-op. This is what public console visitors
see: a replay of a real recorded run, labeled as such, never a live dial.

    uv run python scripts/seed_replay.py
"""

import json
import math
import os
import sqlite3
import wave
from pathlib import Path

from app import db, fsm

FIXTURE = Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json"
RUN_ID = "run_replay_probe_0001"


def _write_tone(dest: Path, seconds: float = 24.0, rate: int = 8000) -> None:
    """A quiet 440Hz sine long enough to cover the replay transcript."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "w") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            sample = int(6000 * math.sin(2 * math.pi * 440 * i / rate))
            frames += sample.to_bytes(2, "little", signed=True)
        out.writeframes(bytes(frames))


def _ensure_tone(conn: "sqlite3.Connection") -> None:
    tone = Path(os.environ.get("ATTEST_AUDIO_DIR", "data/audio")) / f"{RUN_ID}.wav"
    if not tone.is_file():
        _write_tone(tone)
    row = conn.execute("SELECT record_json FROM call_runs WHERE run_id = ?", (RUN_ID,)).fetchone()
    record = json.loads(row[0]) if row and row[0] else {}
    if record.get("audio_note") != "synthetic alignment tone, CI harness only":
        record["audio_note"] = "synthetic alignment tone, CI harness only"
        conn.execute(
            "UPDATE call_runs SET record_json = ? WHERE run_id = ?",
            (json.dumps(record), RUN_ID),
        )
        conn.commit()


def main() -> None:
    payload = json.loads(FIXTURE.read_text())
    conn = db.connect(db.db_path())
    try:
        if db.get_run(conn, RUN_ID) is not None:
            if os.environ.get("ATTEST_SEED_TEST_TONE") == "1":
                # A reused container keeps its DB; the tone and its honest
                # note must still exist or CI exercises nothing.
                _ensure_tone(conn)
            print(f"{RUN_ID} already seeded; nothing to do")
            return
        record = {
            "org": "Example Counseling Center",
            "replay": True,
            "claims": {"accepting_new_patients": "yes", "accepts_plan": "yes"},
        }
        if os.environ.get("ATTEST_SEED_TEST_TONE") == "1":
            # CI harness only, never a deployed judge path: a synthetic tone
            # exists so e2e can exercise the waveform without pretending any
            # real call audio exists. The provenance note is displayed as-is.
            record["audio_note"] = "synthetic alignment tone, CI harness only"
            _write_tone(Path(os.environ.get("ATTEST_AUDIO_DIR", "data/audio")) / f"{RUN_ID}.wav")
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
