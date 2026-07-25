import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pytest

from app import db, fsm
from app.main import app

SECRET = "endpoint-secret-not-real"
FIXTURE = json.loads(
    (Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json").read_text()
)


def _signed_headers(raw: bytes) -> dict[str, str]:
    ts = str(time.time())
    digest = hmac.new(SECRET.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return {"CALL-E-Timestamp": ts, "CALL-E-Signature": f"v1={digest}"}


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _seed_run(database: Path) -> None:
    conn = db.connect(database)
    db.create_run(conn, run_id="run_wh", idempotency_key="run_wh")
    db.set_calle_call_id(conn, "run_wh", str(FIXTURE["id"]))
    fsm.advance(conn, "run_wh", "submitted")
    conn.close()


async def test_valid_webhook_lands_terminal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "wh.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.setenv("CALLE_WEBHOOK_SECRET", SECRET)
    _seed_run(database)

    raw = json.dumps(FIXTURE).encode()
    async with _client() as client:
        response = await client.post("/calle/webhook", content=raw, headers=_signed_headers(raw))
    assert response.status_code == 202

    conn = db.connect(database)
    row = db.get_run(conn, "run_wh")
    assert row is not None and row["state"] == "completed"
    conn.close()


async def test_replayed_webhook_is_a_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "wh2.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.setenv("CALLE_WEBHOOK_SECRET", SECRET)
    _seed_run(database)

    raw = json.dumps(FIXTURE).encode()
    headers = _signed_headers(raw)
    async with _client() as client:
        first = await client.post("/calle/webhook", content=raw, headers=headers)
        second = await client.post("/calle/webhook", content=raw, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 202

    conn = db.connect(database)
    row = db.get_run(conn, "run_wh")
    assert row is not None and row["state"] == "completed"
    conn.close()


async def test_bad_signature_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "wh3.db"))
    monkeypatch.setenv("CALLE_WEBHOOK_SECRET", SECRET)
    raw = json.dumps(FIXTURE).encode()
    headers = _signed_headers(raw)
    headers["CALL-E-Signature"] = "v1=" + "0" * 64
    async with _client() as client:
        response = await client.post("/calle/webhook", content=raw, headers=headers)
    assert response.status_code == 400


async def test_missing_secret_is_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "wh4.db"))
    monkeypatch.delenv("CALLE_WEBHOOK_SECRET", raising=False)
    raw = json.dumps(FIXTURE).encode()
    async with _client() as client:
        response = await client.post("/calle/webhook", content=raw, headers=_signed_headers(raw))
    assert response.status_code == 503
