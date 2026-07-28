"""Seed the database with scrubbed real probe payloads as labeled replays.

Idempotent: running twice is a no-op. This is what public console visitors
see: replays of real recorded runs, labeled as such, never a live dial.

Two replays ship:
- run_replay_probe_0001: the second probe call (transcript only; no audio
  was captured on that call, and the API exposes no recording URL).
- run_replay_builder_0001: a consented builder-line call recorded on the
  receiving end (2026-07-26). Its trimmed, loudness-normalized audio ships
  as a fixture and is copied into ATTEST_AUDIO_DIR at seed time.

    uv run python scripts/seed_replay.py
"""

import json
import math
import os
import shutil
import sqlite3
import wave
from dataclasses import dataclass
from pathlib import Path

from app import db, fsm

FIXTURES = Path(__file__).parent.parent / "mock_calle" / "fixtures"

BUILDER_NOTE = "audio captured on the receiving end of this consented call, builder line"
TONE_NOTE = "synthetic alignment tone, CI harness only"


@dataclass(frozen=True)
class Replay:
    run_id: str
    fixture: str
    record: dict[str, object]
    label: str


REPLAYS = [
    Replay(
        run_id="run_replay_probe_0001",
        fixture="terminal_result.json",
        record={
            "org": "Example Counseling Center",
            "replay": True,
            "claims": {"accepting_new_patients": "yes", "accepts_plan": "yes"},
        },
        label="labeled replay of the scrubbed real probe call",
    ),
    Replay(
        run_id="run_replay_builder_0001",
        fixture="replay_builder_call.json",
        record={
            "org": "Attest builder test line",
            "replay": True,
            "claims": {"accepting_new_patients": "yes"},
            "audio_note": BUILDER_NOTE,
        },
        label="labeled replay of the consented builder-line call, with audio",
    ),
    Replay(
        run_id="run_replay_practice_0001",
        fixture="replay_practice_voicemail.json",
        record={
            # The practice consented in writing to the call and to public use of
            # the transcript, explicitly choosing to remain anonymous. The name,
            # the practitioner, the number, and the website are redacted in the
            # fixture with visible brackets rather than swapped for plausible
            # fictional values, because a fake name can be mistaken for the real
            # one and a bracket cannot.
            "org": "a consenting Atlanta counseling practice",
            "replay": True,
            "claims": {},
        },
        label="labeled replay of a consented call to a real practice; reached voicemail",
    ),
]


def _audio_dir() -> Path:
    return Path(os.environ.get("ATTEST_AUDIO_DIR", "data/audio"))


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


def _set_audio_note(conn: sqlite3.Connection, run_id: str, note: str) -> None:
    row = conn.execute("SELECT record_json FROM call_runs WHERE run_id = ?", (run_id,)).fetchone()
    record = json.loads(row[0]) if row and row[0] else {}
    if record.get("audio_note") != note:
        record["audio_note"] = note
        conn.execute(
            "UPDATE call_runs SET record_json = ? WHERE run_id = ?",
            (json.dumps(record), run_id),
        )
        conn.commit()


def _ensure_tone(conn: sqlite3.Connection) -> None:
    """CI harness only, never a deployed judge path: a synthetic tone lets
    e2e exercise the waveform on the audio-free probe replay without
    pretending real call audio exists. The note is displayed as-is."""
    tone = _audio_dir() / "run_replay_probe_0001.wav"
    if not tone.is_file():
        _write_tone(tone)
    _set_audio_note(conn, "run_replay_probe_0001", TONE_NOTE)


def _ensure_builder_audio() -> None:
    """The real builder-line recording ships with the repo; the seed copies
    it beside the database so the audio endpoint can serve it."""
    source = FIXTURES / "audio" / "run_replay_builder_0001.m4a"
    if not source.is_file():
        return
    dest = _audio_dir() / source.name
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)


def _seed_one(conn: sqlite3.Connection, replay: Replay) -> None:
    run_id = replay.run_id
    if db.get_run(conn, run_id) is not None:
        print(f"{run_id} already seeded; nothing to do")
        return
    payload = json.loads((FIXTURES / replay.fixture).read_text())
    record = dict(replay.record)
    if run_id == "run_replay_probe_0001" and os.environ.get("ATTEST_SEED_TEST_TONE") == "1":
        record["audio_note"] = TONE_NOTE
        _write_tone(_audio_dir() / f"{run_id}.wav")
    db.create_run(conn, run_id=run_id, idempotency_key=run_id, record_json=json.dumps(record))
    db.set_calle_call_id(conn, run_id, str(payload["id"]))
    fsm.advance(conn, run_id, "submitted")
    fsm.advance(conn, run_id, "completed", terminal_payload=json.dumps(payload))
    print(f"seeded {run_id} ({replay.label})")


def main() -> None:
    conn = db.connect(db.db_path())
    try:
        for replay in REPLAYS:
            _seed_one(conn, replay)
        _ensure_builder_audio()
        if os.environ.get("ATTEST_SEED_TEST_TONE") == "1":
            # A reused container keeps its DB; the tone and its honest note
            # must still exist or CI exercises nothing.
            _ensure_tone(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
