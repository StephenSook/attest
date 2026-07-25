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
