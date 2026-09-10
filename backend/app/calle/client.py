"""All CALL-E REST traffic, in one obvious place.

Wraps the official calle-ai SDK (imported as `calle`). The SDK is synchronous,
so every call is offloaded with asyncio.to_thread to keep the event loop free.
If the SDK ever lags the REST surface, this is the one file that changes.
"""

import asyncio
import functools
import hashlib
import hmac
import os
from collections.abc import Mapping
from typing import Any

from calle import CalleClient

JsonObject = dict[str, Any]

_PROD_BASE_URL = "https://api.heycall-e.com"
_DISPATCH_KEY_DOMAIN = b"attest-dispatch-fingerprint-v1\x00"
_CREDENTIAL_FINGERPRINT_DOMAIN = b"attest-credential-fingerprint-v1\x00"


def _default_base_url() -> str:
    if os.environ.get("ATTEST_USE_MOCK", "true").lower() == "true":
        return os.environ.get("ATTEST_MOCK_BASE_URL", "http://localhost:8100")
    return os.environ.get("CALLE_API_BASE_URL", _PROD_BASE_URL)


def is_mock_mode() -> bool:
    """True when calls are served by the local mock rather than the real
    platform. Recorded on every run so a simulated result can never be
    mistaken for a real one."""
    return os.environ.get("ATTEST_USE_MOCK", "true").lower() == "true"


def _dispatch_key(api_key: str) -> bytes:
    return hashlib.sha256(_DISPATCH_KEY_DOMAIN + api_key.encode()).digest()


class CalleService:
    """One outbound verification call at a time. No batching, by design."""

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
        resolved_key = api_key if api_key is not None else os.environ.get("CALLE_API_KEY", "")
        resolved_base_url = base_url if base_url is not None else _default_base_url()
        if not resolved_key:
            # An empty key would produce the header "Bearer " with a trailing
            # space, which h11 rejects as an illegal header value BEFORE any
            # connection, surfacing as a confusing connection error. Use a
            # legal placeholder instead; the live API still 401s it properly.
            resolved_key = "unset-api-key"
        self._base_url = resolved_base_url.rstrip("/")
        self._provider_mode = "mock" if is_mock_mode() else "live"
        self._dispatch_hmac_key = _dispatch_key(resolved_key)
        self._credential_fingerprint = hashlib.sha256(
            _CREDENTIAL_FINGERPRINT_DOMAIN + resolved_key.encode()
        ).hexdigest()
        self._client = CalleClient(
            api_key=resolved_key,
            base_url=self._base_url,
            timeout=30.0,
        )

    def dispatch_identity(self) -> JsonObject:
        """Non-secret identity bound to a recoverable idempotent request."""
        return {
            "base_url": self._base_url,
            "provider": self._provider_mode,
            "credential_fingerprint": self._credential_fingerprint,
        }

    def accepted_call_recovery_status(self, identity: Mapping[str, object]) -> str:
        """Classify whether an accepted call can be read with this transport.

        Endpoint or provider changes are never probed. A missing legacy
        identity or a rotated credential may be probed because a successful
        authenticated read of the exact call id proves that the current
        credential can access the already accepted call. The caller must bind
        that identity before applying the returned snapshot.
        """
        base_url = str(identity.get("base_url") or "")
        provider = str(identity.get("provider") or "")
        credential_fingerprint = str(identity.get("credential_fingerprint") or "")
        if base_url and base_url != self._base_url:
            return "transport_changed"
        if provider and provider != self._provider_mode:
            return "transport_changed"
        if not base_url or not provider or not credential_fingerprint:
            return "legacy_rebind"
        if hmac.compare_digest(credential_fingerprint, self._credential_fingerprint):
            return "match"
        return "credential_rebind"

    def matches_current_configuration(self) -> bool:
        """Detect a cached client after runtime call configuration changes."""
        current_key = os.environ.get("CALLE_API_KEY", "") or "unset-api-key"
        current_base_url = _default_base_url().rstrip("/")
        current_provider = "mock" if is_mock_mode() else "live"
        return (
            self._base_url == current_base_url
            and self._provider_mode == current_provider
            and hmac.compare_digest(self._dispatch_hmac_key, _dispatch_key(current_key))
        )

    def dispatch_digest(self, canonical_request: str) -> str:
        """Key the request digest so a database leak cannot enumerate phones."""
        return hmac.new(
            self._dispatch_hmac_key,
            canonical_request.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def place_call(
        self,
        *,
        task: str,
        phone: str,
        result_schema: JsonObject | None = None,
        idempotency_key: str,
        metadata: JsonObject | None = None,
        webhook_url: str | None = None,
    ) -> JsonObject:
        # Observed 2026-07-25 against api.heycall-e.com: the live API rejects
        # BOTH result_schema and recipient_result_schema ("... is not supported")
        # even though the SDK exposes them and the maintainers announced the
        # latter. Schema is therefore optional here; extraction and span
        # grounding are our own post-call layer and never depended on it.
        create = functools.partial(
            self._client.calls.create,
            task=task,
            recipient={"phone": phone},
            metadata=metadata,
            webhook_url=webhook_url,
            idempotency_key=idempotency_key,
        )
        if result_schema is not None:
            create = functools.partial(create, recipient_result_schema=result_schema)
        return await asyncio.to_thread(create)

    async def get_call(self, call_id: str) -> JsonObject:
        return await asyncio.to_thread(self._client.calls.get, call_id)

    async def list_events(self, call_id: str, *, cursor: str | None = None) -> JsonObject:
        return await asyncio.to_thread(self._client.calls.list_events, call_id, cursor=cursor)

    def close(self) -> None:
        self._client.close()
