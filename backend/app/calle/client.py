"""All CALL-E REST traffic, in one obvious place.

Wraps the official calle-ai SDK (imported as `calle`). The SDK is synchronous,
so every call is offloaded with asyncio.to_thread to keep the event loop free.
If the SDK ever lags the REST surface, this is the one file that changes.
"""

import asyncio
import os
from typing import Any

from calle import CalleClient

JsonObject = dict[str, Any]

_PROD_BASE_URL = "https://api.heycall-e.com"


def _default_base_url() -> str:
    if os.environ.get("ATTEST_USE_MOCK", "true").lower() == "true":
        return os.environ.get("ATTEST_MOCK_BASE_URL", "http://localhost:8100")
    return os.environ.get("CALLE_API_BASE_URL", _PROD_BASE_URL)


class CalleService:
    """One outbound verification call at a time. No batching, by design."""

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
        self._client = CalleClient(
            api_key=api_key if api_key is not None else os.environ.get("CALLE_API_KEY", ""),
            base_url=base_url if base_url is not None else _default_base_url(),
        )

    async def place_call(
        self,
        *,
        task: str,
        phone: str,
        result_schema: JsonObject,
        idempotency_key: str,
        metadata: JsonObject | None = None,
        webhook_url: str | None = None,
    ) -> JsonObject:
        return await asyncio.to_thread(
            self._client.calls.create,
            task=task,
            recipient={"phone": phone},
            result_schema=result_schema,
            metadata=metadata,
            webhook_url=webhook_url,
            idempotency_key=idempotency_key,
        )

    async def get_call(self, call_id: str) -> JsonObject:
        return await asyncio.to_thread(self._client.calls.get, call_id)

    async def list_events(self, call_id: str, *, cursor: str | None = None) -> JsonObject:
        return await asyncio.to_thread(self._client.calls.list_events, call_id, cursor=cursor)

    def close(self) -> None:
        self._client.close()
