"""The judge sandbox dials only the requester's own number, once, with
explicit consent, under a global cap, behind a kill switch. Every rail is
pinned here because this endpoint is the only outward-dialing surface a
non-operator can reach."""

import json

import httpx
import pytest
import respx
from calle.errors import CalleTimeoutError
from httpx import Response

from app import db, fsm
from app.main import app

HEADERS_JUDGE = {"X-Attest-Key": "judge-key"}
HEADERS_OPERATOR = {"X-Attest-Key": "operator-key"}
BODY = {
    "phone": "+15550101234",
    "org": "Judge Demo",
    "claims": {"accepting_new_patients": "yes"},
    "consent": True,
}


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "sandbox.db"))
    monkeypatch.setenv("ATTEST_JUDGE_KEY", "judge-key")
    monkeypatch.setenv("ATTEST_OPERATOR_KEY", "operator-key")
    monkeypatch.setenv("ATTEST_SANDBOX_ENABLED", "1")
    monkeypatch.setenv("ATTEST_USE_MOCK", "true")
    monkeypatch.setenv("ATTEST_MOCK_BASE_URL", "http://mock.invalid")
    # Fresh service per test so the base URL env is re-read.
    if hasattr(app.state, "calle_service"):
        del app.state.calle_service


async def test_judge_requires_consent() -> None:
    async with _client() as client:
        response = await client.post(
            "/internal/runs", json={**BODY, "consent": False}, headers=HEADERS_JUDGE
        )
    assert response.status_code == 422
    assert "consent" in response.json()["detail"]


async def test_kill_switch_disables_the_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTEST_SANDBOX_ENABLED", "0")
    async with _client() as client:
        response = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)
    assert response.status_code == 503


async def test_sandbox_defaults_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATTEST_SANDBOX_ENABLED")
    async with _client() as client:
        response = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)
    assert response.status_code == 503


@respx.mock
async def test_same_number_never_gets_two_demo_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.post("http://mock.invalid/v1/calls").mock(
        return_value=Response(201, json={"id": "call_sbx_1", "status": "queued"})
    )
    async with _client() as client:
        first = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)
        second = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)
    assert first.status_code == 201
    assert second.status_code == 429
    assert "already received" in second.json()["detail"]


@respx.mock
async def test_ambiguous_submit_keeps_the_reservation() -> None:
    respx.post("http://mock.invalid/v1/calls").mock(side_effect=CalleTimeoutError("timed out"))
    async with _client() as client:
        with pytest.raises(CalleTimeoutError):
            await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)

    conn = db.connect(db.db_path())
    try:
        assert db.reserve_sandbox_slot(conn, "unused", cap=1) == "capped"
    finally:
        conn.close()


async def test_judge_runs_never_enter_the_public_ledger() -> None:
    conn = db.connect(db.db_path())
    try:
        db.create_run(
            conn,
            run_id="run_private_judge",
            idempotency_key="run_private_judge",
            record_json=json.dumps({"org": "Private judge run", "judge_sandbox": True}),
        )
        db.set_calle_call_id(conn, "run_private_judge", "call_private_judge")
        fsm.advance(conn, "run_private_judge", "submitted")
        fsm.advance(
            conn,
            "run_private_judge",
            "failed",
            terminal_payload=json.dumps({"status": "failed", "error": "private transcript"}),
        )
    finally:
        conn.close()

    async with _client() as client:
        ledger = await client.get("/api/runs")
        detail = await client.get("/api/runs/run_private_judge")
        attestation = await client.get("/api/runs/run_private_judge/attestation")
        audio = await client.get("/api/runs/run_private_judge/audio")

    assert all(item["run_id"] != "run_private_judge" for item in ledger.json()["runs"])
    assert detail.status_code == 404
    assert attestation.status_code == 404
    assert audio.status_code == 404


async def test_global_cap_closes_the_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTEST_SANDBOX_CAP", "0")
    # Cap is read at import time by default; enforce via a fresh read.
    from app import main as main_module

    monkeypatch.setattr(main_module, "_SANDBOX_CAP", 0)
    async with _client() as client:
        response = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)
    assert response.status_code == 429
    assert "budget" in response.json()["detail"]


@respx.mock
async def test_operator_key_is_not_railed(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.post("http://mock.invalid/v1/calls").mock(
        return_value=Response(201, json={"id": "call_op_1", "status": "queued"})
    )
    from app import main as main_module

    monkeypatch.setattr(main_module, "_SANDBOX_CAP", 0)
    async with _client() as client:
        response = await client.post(
            "/internal/runs", json={**BODY, "consent": False}, headers=HEADERS_OPERATOR
        )
    # No consent, cap zero: the operator path ignores both rails entirely.
    assert response.status_code == 201


async def test_wrong_key_is_forbidden_and_no_key_unconfigured_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _client() as client:
        assert (
            await client.post("/internal/runs", json=BODY, headers={"X-Attest-Key": "nope"})
        ).status_code == 403
    monkeypatch.delenv("ATTEST_JUDGE_KEY")
    monkeypatch.delenv("ATTEST_OPERATOR_KEY")
    async with _client() as client:
        assert (
            await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)
        ).status_code == 503


def test_reservation_is_atomic_for_cap_and_dedup(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """The reservation transaction enforces cap and dedup even if the
    endpoint's lock were bypassed: this pins the db-level guarantee."""
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "resv.db"))
    from app import db

    conn = db.connect(db.db_path())
    try:
        assert db.reserve_sandbox_slot(conn, "hashA", cap=2) == "ok"
        assert db.reserve_sandbox_slot(conn, "hashA", cap=2) == "duplicate"
        assert db.reserve_sandbox_slot(conn, "hashB", cap=2) == "ok"
        assert db.reserve_sandbox_slot(conn, "hashC", cap=2) == "capped"
        db.release_sandbox_slot(conn, "hashB")
        assert db.reserve_sandbox_slot(conn, "hashC", cap=2) == "ok"
    finally:
        conn.close()


async def test_premium_and_toll_numbers_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _client() as client:
        # 950 was accepted before: the old check sliced the wrong offset.
        for bad in ("+19005551234", "+19765551234", "+19501234567"):
            response = await client.post(
                "/internal/runs", json={**BODY, "phone": bad}, headers=HEADERS_JUDGE
            )
            assert response.status_code == 422, bad
