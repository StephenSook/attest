"""Regression: an empty API key must not poison the HTTP client.

An empty key produced the header "Bearer " (trailing space), which h11
rejects as an illegal header value before any connection, surfacing as a
misleading connection error in credential-less mock deployments.
"""

import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from app.calle.client import CalleService

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json").read_text()
)


@respx.mock
async def test_empty_env_key_still_speaks_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CALLE_API_KEY", raising=False)
    route = respx.post("https://calle.test/v1/calls").mock(
        return_value=Response(201, json=FIXTURE)
    )
    service = CalleService(base_url="https://calle.test")
    result = await service.place_call(
        task="verify", phone="+15550101234", idempotency_key="empty-key-test"
    )
    assert result["status"] == "completed"
    auth = route.calls.last.request.headers["Authorization"]
    assert auth == "Bearer unset-api-key"
    service.close()
