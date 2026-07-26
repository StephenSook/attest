"""Run audio: local files only, honest 404s, correct media types.

The CALL-E API exposes no recording URL (verified against the live payload
and the SDK source, 2026-07-26), so run audio is whatever an operator
captured on our own end of a consented call and placed in ATTEST_AUDIO_DIR.
The endpoint must never fetch anything remote.
"""

import json
from pathlib import Path

import httpx
import pytest

from app import db, fsm
from app.main import app

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json").read_text()
)


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _seed(database: Path, audio_note: str | None = None) -> None:
    conn = db.connect(database)
    record: dict[str, object] = {"org": "Example Counseling Center", "replay": True}
    if audio_note:
        record["audio_note"] = audio_note
    db.create_run(
        conn, run_id="run_audio", idempotency_key="run_audio", record_json=json.dumps(record)
    )
    db.set_calle_call_id(conn, "run_audio", str(FIXTURE["id"]))
    fsm.advance(conn, "run_audio", "submitted")
    fsm.advance(conn, "run_audio", "completed", terminal_payload=json.dumps(FIXTURE))
    conn.close()


async def test_audio_404_when_none_and_has_audio_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("ATTEST_AUDIO_DIR", str(tmp_path / "audio"))
    _seed(tmp_path / "a.db")
    async with _client() as client:
        detail = (await client.get("/api/runs/run_audio")).json()
        assert detail["has_audio"] is False
        assert "audio_note" not in detail
        assert (await client.get("/api/runs/run_audio/audio")).status_code == 404


async def test_audio_served_with_media_type_and_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "a.db"))
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "run_audio.wav").write_bytes(b"RIFF0000WAVEfmt ")
    monkeypatch.setenv("ATTEST_AUDIO_DIR", str(audio_dir))
    _seed(tmp_path / "a.db", audio_note="synthetic alignment tone, CI harness only")
    async with _client() as client:
        detail = (await client.get("/api/runs/run_audio")).json()
        assert detail["has_audio"] is True
        assert detail["audio_note"] == "synthetic alignment tone, CI harness only"
        response = await client.get("/api/runs/run_audio/audio")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/wav")


async def test_audio_404_for_unknown_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("ATTEST_AUDIO_DIR", str(tmp_path / "audio"))
    async with _client() as client:
        assert (await client.get("/api/runs/run_nope/audio")).status_code == 404
