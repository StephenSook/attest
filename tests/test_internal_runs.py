import json
from pathlib import Path

import httpx
import pytest
import respx
from httpx import Response

from app import db
from app.main import app

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json").read_text()
)
MOCK_BASE = "http://localhost:8100"


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_unconfigured_key_fails_closed_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.delenv("ATTEST_JUDGE_KEY", raising=False)
    async with _client() as client:
        response = await client.post(
            "/internal/runs", json={"org": "Test Practice", "phone": "+15550101234"}
        )
    assert response.status_code == 503


async def test_wrong_key_403(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "b.db"))
    monkeypatch.setenv("ATTEST_JUDGE_KEY", "right-key")
    async with _client() as client:
        response = await client.post(
            "/internal/runs",
            json={"org": "Test Practice", "phone": "+15550101234"},
            headers={"X-Attest-Key": "wrong-key"},
        )
    assert response.status_code == 403


@respx.mock
async def test_correct_key_creates_submitted_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "c.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.setenv("ATTEST_JUDGE_KEY", "right-key")
    monkeypatch.setenv("ATTEST_USE_MOCK", "true")
    app.state.calle_service = None  # force a fresh service against the mocked base
    respx.post(f"{MOCK_BASE}/v1/calls").mock(return_value=Response(201, json=FIXTURE))

    async with _client() as client:
        response = await client.post(
            "/internal/runs",
            json={"org": "Test Practice", "phone": "+15550101234"},
            headers={"X-Attest-Key": "right-key"},
        )
    assert response.status_code == 201
    run_id = response.json()["run_id"]

    conn = db.connect(database)
    row = db.get_run(conn, run_id)
    assert row is not None and row["state"] == "submitted"
    assert row["calle_call_id"] == FIXTURE["id"]
    conn.close()


async def test_invalid_phone_shape_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "d.db"))
    monkeypatch.setenv("ATTEST_JUDGE_KEY", "right-key")
    async with _client() as client:
        response = await client.post(
            "/internal/runs",
            json={"org": "Test Practice", "phone": "not-a-number"},
            headers={"X-Attest-Key": "right-key"},
        )
    assert response.status_code == 422
