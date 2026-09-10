import json
from pathlib import Path

import httpx
import pytest
import respx
from calle.errors import CalleTimeoutError
from httpx import Response

from app import db
from app.main import app

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json").read_text()
)
MOCK_BASE = "http://localhost:8100"
RUN_HEADERS = {
    "X-Attest-Key": "right-key",
    "X-Attest-Run-Token": "test-run-capability-token-1234567890abcdef",
}


@pytest.fixture(autouse=True)
def _destination_hash_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTEST_PHONE_HASH_KEY", "test-destination-hash-key")


def _body(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "request_id": "c" * 32,
        "org": "Test Practice",
        "phone": "+15550101234",
    }
    body.update(changes)
    return body


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_unconfigured_key_fails_closed_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.delenv("ATTEST_JUDGE_KEY", raising=False)
    async with _client() as client:
        response = await client.post("/internal/runs", json=_body())
    assert response.status_code == 503


async def test_wrong_key_403(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "b.db"))
    monkeypatch.setenv("ATTEST_JUDGE_KEY", "right-key")
    async with _client() as client:
        response = await client.post(
            "/internal/runs",
            json=_body(),
            headers={"X-Attest-Key": "wrong-key"},
        )
    assert response.status_code == 403


@respx.mock
async def test_correct_key_creates_submitted_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "c.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.setenv("ATTEST_OPERATOR_KEY", "right-key")
    monkeypatch.setenv("ATTEST_JUDGE_KEY", "judge-only")
    monkeypatch.setenv("ATTEST_USE_MOCK", "true")
    app.state.calle_service = None  # force a fresh service against the mocked base
    respx.post(f"{MOCK_BASE}/v1/calls").mock(return_value=Response(201, json=FIXTURE))

    async with _client() as client:
        response = await client.post(
            "/internal/runs",
            json=_body(),
            headers=RUN_HEADERS,
        )
    assert response.status_code == 201
    run_id = response.json()["run_id"]

    conn = db.connect(database)
    row = db.get_run(conn, run_id)
    assert row is not None and row["state"] == "submitted"
    assert row["calle_call_id"] == FIXTURE["id"]
    conn.close()


@respx.mock
async def test_product_run_registers_the_public_webhook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "webhook.db"))
    monkeypatch.setenv("ATTEST_OPERATOR_KEY", "right-key")
    monkeypatch.setenv("ATTEST_PUBLIC_BASE_URL", "https://attest.example/")
    monkeypatch.setenv("ATTEST_USE_MOCK", "true")
    app.state.calle_service = None
    route = respx.post(f"{MOCK_BASE}/v1/calls").mock(return_value=Response(201, json=FIXTURE))

    async with _client() as client:
        response = await client.post(
            "/internal/runs",
            json=_body(),
            headers=RUN_HEADERS,
        )

    assert response.status_code == 201
    request_body = json.loads(route.calls.last.request.content)
    assert request_body["webhook_url"] == "https://attest.example/calle/webhook"


@respx.mock
async def test_expired_operator_retry_never_posts_a_second_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "operator-expired.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.setenv("ATTEST_OPERATOR_KEY", "right-key")
    monkeypatch.setenv("ATTEST_USE_MOCK", "true")
    app.state.calle_service = None
    route = respx.post(f"{MOCK_BASE}/v1/calls").mock(
        side_effect=CalleTimeoutError("response lost after acceptance")
    )

    async with _client() as client:
        with pytest.raises(CalleTimeoutError):
            await client.post("/internal/runs", json=_body(), headers=RUN_HEADERS)

        conn = db.connect(database)
        try:
            conn.execute("UPDATE call_runs SET dispatch_expires_at = 0, submit_lease_until = 0")
            conn.commit()
        finally:
            conn.close()

        expired = await client.post("/internal/runs", json=_body(), headers=RUN_HEADERS)

    assert expired.status_code == 409
    assert expired.json()["detail"]["code"] == "call_request_not_retried"
    assert route.call_count == 1


@respx.mock
async def test_expired_destination_blocks_fresh_id_after_a_b_a_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "operator-destination-guard.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.setenv("ATTEST_OPERATOR_KEY", "right-key")
    monkeypatch.setenv("ATTEST_USE_MOCK", "true")
    app.state.calle_service = None
    route = respx.post(f"{MOCK_BASE}/v1/calls").mock(
        side_effect=[
            CalleTimeoutError("response lost after acceptance"),
            Response(201, json={**FIXTURE, "id": "call_destination_b"}),
        ]
    )
    body_a = _body(request_id="a" * 32, phone="+15550101234")
    body_b = _body(request_id="b" * 32, phone="+15550105678")
    body_a_fresh = _body(request_id="d" * 32, phone="+15550101234")

    async with _client() as client:
        with pytest.raises(CalleTimeoutError):
            await client.post("/internal/runs", json=body_a, headers=RUN_HEADERS)
        conn = db.connect(database)
        try:
            conn.execute(
                "UPDATE call_runs SET dispatch_expires_at = 0, submit_lease_until = 0 "
                "WHERE run_id = ?",
                ("run_" + "a" * 32,),
            )
            conn.commit()
            assert db.expire_submission_attempts(conn) == 1
        finally:
            conn.close()
        unrelated = await client.post("/internal/runs", json=body_b, headers=RUN_HEADERS)
        blocked = await client.post("/internal/runs", json=body_a_fresh, headers=RUN_HEADERS)

    assert unrelated.status_code == 201
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "call_destination_unreconciled"
    assert route.call_count == 2


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
