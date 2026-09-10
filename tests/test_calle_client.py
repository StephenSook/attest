import json
from pathlib import Path
from typing import Any

import respx
from httpx import Response

from app.calle import CalleService
from app.models import verification_result_schema

BASE = "https://calle.test"
FIXTURE = json.loads(
    (Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json").read_text()
)


def _service() -> CalleService:
    return CalleService(api_key="test-key-not-real", base_url=BASE)


def test_accepted_call_recovery_distinguishes_rotation_from_endpoint_change() -> None:
    service = _service()
    identity = service.dispatch_identity()
    assert service.accepted_call_recovery_status(identity) == "match"
    assert (
        service.accepted_call_recovery_status(
            {**identity, "credential_fingerprint": "rotated-credential"}
        )
        == "credential_rebind"
    )
    assert (
        service.accepted_call_recovery_status(
            {"base_url": None, "provider": None, "credential_fingerprint": None}
        )
        == "legacy_rebind"
    )
    assert (
        service.accepted_call_recovery_status(
            {**identity, "base_url": "https://different-provider.test"}
        )
        == "transport_changed"
    )
    service.close()


@respx.mock
async def test_readiness_probe_uses_harmless_missing_call_and_caches_success() -> None:
    route = respx.get(f"{BASE}/v1/calls/call_attest_readiness_probe_v1").mock(
        return_value=Response(
            404,
            json={"error": {"code": "not_found", "message": "call not found"}},
        )
    )
    service = _service()
    try:
        assert await service.probe_readiness() == (True, None)
        assert await service.probe_readiness() == (True, None)
    finally:
        service.close()
    assert route.call_count == 1


@respx.mock
async def test_readiness_probe_reports_rejected_credentials() -> None:
    respx.get(f"{BASE}/v1/calls/call_attest_readiness_probe_v1").mock(
        return_value=Response(
            401,
            json={"error": {"code": "unauthorized", "message": "bad key"}},
        )
    )
    service = _service()
    try:
        assert await service.probe_readiness() == (False, "provider_auth_rejected")
    finally:
        service.close()


@respx.mock
async def test_place_call_posts_task_schema_and_idempotency_key() -> None:
    route = respx.post(f"{BASE}/v1/calls").mock(return_value=Response(201, json=FIXTURE))
    service = _service()
    result = await service.place_call(
        task="Verify whether the office is accepting new patients.",
        phone="+15550101234",
        result_schema=verification_result_schema(),
        idempotency_key="attest-test-0001",
    )
    assert result["status"] == "completed"
    request = route.calls.last.request
    assert request.headers["Idempotency-Key"] == "attest-test-0001"
    assert request.headers["Authorization"] == "Bearer test-key-not-real"
    body: dict[str, Any] = json.loads(request.content)
    assert body["recipients"] == [{"phones": ["+15550101234"]}]
    assert body["recipient_result_schema"]["additionalProperties"] is False
    service.close()


@respx.mock
async def test_get_call_and_list_events() -> None:
    respx.get(f"{BASE}/v1/calls/call_mock_1").mock(return_value=Response(200, json=FIXTURE))
    respx.get(f"{BASE}/v1/calls/call_mock_1/events").mock(
        return_value=Response(200, json={"events": []})
    )
    service = _service()
    call = await service.get_call("call_mock_1")
    events = await service.list_events("call_mock_1")
    assert call["task_completed"] is True
    assert call["completion_confidence"]["label"] == "high"
    assert events["events"] == []
    service.close()
