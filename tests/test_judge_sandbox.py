"""The judge sandbox dials only the requester's own number, once, with
explicit consent, under a global cap, behind a kill switch. Every rail is
pinned here because this endpoint is the only outward-dialing surface a
non-operator can reach."""

import hashlib
import json

import httpx
import pytest
import respx
from calle.errors import CalleAPIError, CalleTimeoutError
from httpx import Response

from app import db, fsm
from app.main import app

RUN_TOKEN = "test-run-capability-token-1234567890abcdef"
HEADERS_JUDGE = {
    "X-Attest-Key": "judge-key",
    "X-Attest-Run-Token": RUN_TOKEN,
}
HEADERS_OPERATOR = {
    "X-Attest-Key": "operator-key",
    "X-Attest-Run-Token": RUN_TOKEN,
}
BODY = {
    "request_id": "a" * 32,
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
    monkeypatch.setenv("ATTEST_PHONE_HASH_KEY", "test-phone-hash-key")
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
        second = await client.post(
            "/internal/runs",
            json={**BODY, "request_id": "b" * 32},
            headers=HEADERS_JUDGE,
        )
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


@respx.mock
async def test_accepted_response_without_id_keeps_the_reservation() -> None:
    """A malformed success can arrive after CALL-E accepted the call."""
    respx.post("http://mock.invalid/v1/calls").mock(
        return_value=Response(201, json={"status": "queued"})
    )
    async with _client() as client:
        with pytest.raises(RuntimeError, match="no call id"):
            await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)

    conn = db.connect(db.db_path())
    try:
        assert db.reserve_sandbox_slot(conn, "unused", cap=1) == "capped"
    finally:
        conn.close()


@pytest.mark.parametrize(
    "record",
    [
        {"org": "Private judge run", "judge_sandbox": True, "provider": "live"},
        {"org": "Private operator run", "provider": "live"},
        {"org": "Private mock run", "judge_sandbox": True, "provider": "mock"},
    ],
)
async def test_unpublished_runs_never_enter_public_endpoints(
    record: dict[str, object],
) -> None:
    run_id = "run_" + str(record["org"]).lower().replace(" ", "_")
    conn = db.connect(db.db_path())
    try:
        db.create_run(
            conn,
            run_id=run_id,
            idempotency_key=run_id,
            record_json=json.dumps(record),
        )
        db.set_calle_call_id(conn, run_id, "call_" + run_id)
        fsm.advance(conn, run_id, "submitted")
        fsm.advance(
            conn,
            run_id,
            "failed",
            terminal_payload=json.dumps({"status": "failed", "error": "private transcript"}),
        )
    finally:
        conn.close()

    async with _client() as client:
        ledger = await client.get("/api/runs")
        detail = await client.get(f"/api/runs/{run_id}")
        attestation = await client.get(f"/api/runs/{run_id}/attestation")
        audio = await client.get(f"/api/runs/{run_id}/audio")

    assert all(item["run_id"] != run_id for item in ledger.json()["runs"])
    assert detail.status_code == 404
    assert attestation.status_code == 404
    assert audio.status_code == 404


@respx.mock
async def test_private_run_capability_reveals_only_its_redacted_detail() -> None:
    """A fresh call stays off the public API but remains usable by the
    browser that created it. The raw capability must never be persisted."""
    respx.post("http://mock.invalid/v1/calls").mock(
        return_value=Response(201, json={"id": "call_private_1", "status": "queued"})
    )
    async with _client() as client:
        created = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)
        run_id = created.json()["run_id"]
        access_token = created.json()["access_token"]

        public = await client.get(f"/api/runs/{run_id}")
        missing = await client.get(f"/internal/runs/{run_id}")
        wrong = await client.get(
            f"/internal/runs/{run_id}", headers={"X-Attest-Run-Token": "wrong"}
        )
        granted = await client.get(
            f"/internal/runs/{run_id}",
            headers={"X-Attest-Run-Token": access_token},
        )

    assert public.status_code == 404
    assert missing.status_code == 404
    assert wrong.status_code == 404
    assert granted.status_code == 200
    assert granted.headers["cache-control"] == "private, no-store"
    assert granted.json()["run_id"] == run_id
    assert granted.json()["published"] is False

    conn = db.connect(db.db_path())
    try:
        row = db.get_run(conn, run_id)
        assert row is not None
        record = json.loads(str(row["record_json"]))
    finally:
        conn.close()
    assert access_token not in json.dumps(record)
    assert len(record["access_token_sha256"]) == 64
    database_bytes = b"".join(
        path.read_bytes() for path in db.db_path().parent.glob(f"{db.db_path().name}*")
    )
    phone = str(BODY["phone"])
    assert phone.encode() not in database_bytes
    assert hashlib.sha256(phone.encode()).hexdigest().encode() not in database_bytes


@pytest.mark.parametrize("headers", [HEADERS_JUDGE, HEADERS_OPERATOR])
@respx.mock
async def test_lost_create_response_retries_with_the_same_provider_key(
    headers: dict[str, str],
) -> None:
    """A client that loses the first response can repeat the same request.

    CALL-E receives the identical idempotency key, so even a first request
    accepted before the timeout cannot ring the destination twice.
    """
    route = respx.post("http://mock.invalid/v1/calls").mock(
        side_effect=[
            CalleTimeoutError("response lost after submit"),
            Response(201, json={"id": "call_retry_1", "status": "queued"}),
        ]
    )
    async with _client() as client:
        with pytest.raises(CalleTimeoutError):
            await client.post("/internal/runs", json=BODY, headers=headers)
        retried = await client.post("/internal/runs", json=BODY, headers=headers)

    assert retried.status_code == 201
    assert retried.json() == {
        "run_id": f"run_{BODY['request_id']}",
        "access_token": RUN_TOKEN,
    }
    assert [call.request.headers["Idempotency-Key"] for call in route.calls] == [
        f"run_{BODY['request_id']}",
        f"run_{BODY['request_id']}",
    ]


@respx.mock
async def test_malformed_accepted_response_retries_with_the_same_provider_key() -> None:
    """A truncated success body can arrive after the provider accepted the call."""
    route = respx.post("http://mock.invalid/v1/calls").mock(
        side_effect=[
            Response(201, content=b"{"),
            Response(201, json={"id": "call_retry_malformed", "status": "queued"}),
        ]
    )
    async with _client() as client:
        with pytest.raises(json.JSONDecodeError):
            await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)
        retried = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)

    assert retried.status_code == 201
    assert [call.request.headers["Idempotency-Key"] for call in route.calls] == [
        f"run_{BODY['request_id']}",
        f"run_{BODY['request_id']}",
    ]


@respx.mock
async def test_ambiguous_server_error_retries_with_the_same_provider_key() -> None:
    route = respx.post("http://mock.invalid/v1/calls").mock(
        side_effect=[
            Response(
                500,
                json={"error": {"code": "internal_error", "message": "try again"}},
            ),
            Response(201, json={"id": "call_retry_500", "status": "queued"}),
        ]
    )
    async with _client() as client:
        with pytest.raises(CalleAPIError):
            await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)
        retried = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)

    assert retried.status_code == 201
    assert [call.request.headers["Idempotency-Key"] for call in route.calls] == [
        f"run_{BODY['request_id']}",
        f"run_{BODY['request_id']}",
    ]


@pytest.mark.parametrize("provider_status", [400, 401, 403, 404, 422, 429])
@respx.mock
async def test_definite_provider_rejection_releases_slot_and_allows_fresh_request(
    provider_status: int,
) -> None:
    route = respx.post("http://mock.invalid/v1/calls").mock(
        side_effect=[
            Response(
                provider_status,
                json={"error": {"code": "rejected", "message": "not accepted"}},
            ),
            Response(201, json={"id": "call_after_rejection", "status": "queued"}),
        ]
    )
    second_body = {**BODY, "request_id": "b" * 32}
    async with _client() as client:
        rejected = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)
        retried = await client.post("/internal/runs", json=second_body, headers=HEADERS_JUDGE)

    assert rejected.status_code == 502
    assert rejected.json()["detail"]["code"] == "call_rejected_before_acceptance"
    assert retried.status_code == 201
    assert len(route.calls) == 2

    conn = db.connect(db.db_path())
    try:
        first = db.get_run(conn, f"run_{BODY['request_id']}")
        second = db.get_run(conn, f"run_{second_body['request_id']}")
        reservations = conn.execute("SELECT COUNT(*) FROM sandbox_reservations").fetchone()[0]
        assert first is not None and first["state"] == "failed"
        assert second is not None and second["state"] == "submitted"
        assert reservations == 1
    finally:
        conn.close()


@respx.mock
async def test_lost_definite_rejection_response_replays_without_provider_resubmit() -> None:
    route = respx.post("http://mock.invalid/v1/calls").mock(
        return_value=Response(
            400,
            json={"error": {"code": "rejected", "message": "not accepted"}},
        )
    )
    async with _client() as client:
        first = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)
        # Treat the first response as lost and repeat the exact browser request.
        replayed = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)

    assert first.status_code == 502
    assert replayed.status_code == 502
    assert replayed.json()["detail"]["code"] == "call_rejected_before_acceptance"
    assert len(route.calls) == 1
    conn = db.connect(db.db_path())
    try:
        reservations = conn.execute("SELECT COUNT(*) FROM sandbox_reservations").fetchone()[0]
        assert reservations == 0
    finally:
        conn.close()


@respx.mock
async def test_request_identity_rejects_wrong_capability_or_changed_payload() -> None:
    route = respx.post("http://mock.invalid/v1/calls").mock(
        return_value=Response(201, json={"id": "call_identity_1", "status": "queued"})
    )
    async with _client() as client:
        first = await client.post("/internal/runs", json=BODY, headers=HEADERS_OPERATOR)
        wrong_token = await client.post(
            "/internal/runs",
            json=BODY,
            headers={**HEADERS_OPERATOR, "X-Attest-Run-Token": "x" * 64},
        )
        changed = await client.post(
            "/internal/runs",
            json={**BODY, "org": "Different Practice"},
            headers=HEADERS_OPERATOR,
        )

    assert first.status_code == 201
    assert wrong_token.status_code == 404
    assert changed.status_code == 409
    assert len(route.calls) == 1


async def test_service_setup_failure_cannot_spend_a_judge_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as main_module

    def broken_service() -> None:
        raise RuntimeError("service setup failed")

    monkeypatch.setattr(main_module, "_get_service", broken_service)
    async with _client() as client:
        with pytest.raises(RuntimeError, match="service setup failed"):
            await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)

    conn = db.connect(db.db_path())
    try:
        assert db.reserve_sandbox_slot(conn, "unused", cap=1) == "ok"
    finally:
        conn.close()


async def test_missing_live_credentials_cannot_spend_a_judge_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATTEST_USE_MOCK", "false")
    monkeypatch.delenv("CALLE_API_KEY", raising=False)

    async with _client() as client:
        response = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)

    assert response.status_code == 503
    assert "credentials" in response.json()["detail"]
    conn = db.connect(db.db_path())
    try:
        assert db.reserve_sandbox_slot(conn, "unused", cap=1) == "ok"
    finally:
        conn.close()


async def test_missing_phone_hash_key_cannot_spend_a_judge_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ATTEST_PHONE_HASH_KEY")

    async with _client() as client:
        response = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)

    assert response.status_code == 503
    assert "deduplication" in response.json()["detail"]
    conn = db.connect(db.db_path())
    try:
        assert db.reserve_sandbox_slot(conn, "unused", cap=1) == "ok"
    finally:
        conn.close()


async def test_cached_service_provider_mismatch_cannot_spend_a_judge_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as main_module
    from app.calle.client import CalleService

    cached_service = CalleService(api_key="test-key-not-real", base_url="http://mock.invalid")
    app.state.calle_service = cached_service
    monkeypatch.setenv("ATTEST_USE_MOCK", "false")
    monkeypatch.setenv("CALLE_API_KEY", "test-key-not-real")
    try:
        async with _client() as client:
            response = await client.post("/internal/runs", json=BODY, headers=HEADERS_JUDGE)

        assert response.status_code == 503
        assert "configuration changed" in response.json()["detail"]
        conn = db.connect(db.db_path())
        try:
            assert db.reserve_sandbox_slot(conn, "unused", cap=1) == "ok"
        finally:
            conn.close()
    finally:
        cached_service.close()
        if hasattr(main_module.app.state, "calle_service"):
            del main_module.app.state.calle_service


def test_sandbox_run_and_reservation_are_one_transaction(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A run-id conflict must roll back the phone reservation with it."""
    database = tmp_path / "atomic.db"
    conn = db.connect(database)
    try:
        db.create_run(conn, run_id="run_conflict", idempotency_key="run_conflict")
        outcome = db.create_sandbox_run(
            conn,
            phone_hash="phone-a",
            cap=1,
            run_id="run_conflict",
            idempotency_key="run_conflict",
            record_json="{}",
        )
        assert outcome == "request_exists"
        assert (
            db.create_sandbox_run(
                conn,
                phone_hash="phone-a",
                cap=1,
                run_id="run_new",
                idempotency_key="run_new",
                record_json="{}",
            )
            == "ok"
        )
    finally:
        conn.close()


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
