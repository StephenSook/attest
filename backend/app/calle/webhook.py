"""Terminal webhook verification.

Signature scheme (confirmed by reading the calle-ai SDK source, calle/webhooks.py):
HMAC-SHA256 over `timestamp + "." + raw_body` with the webhook secret, sent as
`CALL-E-Signature: v1=<hexdigest>` alongside `CALL-E-Timestamp`.

The SDK verifies the signature but NOT the timestamp window, so replayed
deliveries with a stale timestamp would pass it. This wrapper adds the
five-minute window on top. Verification runs over the exact raw bytes,
before any JSON parsing.
"""

import time
from collections.abc import Mapping
from typing import Any

from calle.errors import CalleWebhookSignatureError
from calle.webhooks import CalleWebhooks

TIMESTAMP_WINDOW_SECONDS = 300

_webhooks = CalleWebhooks()


class WebhookVerificationError(Exception):
    pass


def verify_and_parse_webhook(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    secret: str,
    now: float | None = None,
) -> dict[str, Any]:
    """Verify signature and timestamp window, then parse. Raises on any failure."""
    timestamp = _header(headers, "CALL-E-Timestamp")
    if timestamp is None:
        raise WebhookVerificationError("Missing CALL-E-Timestamp header.")
    try:
        sent_at = float(timestamp)
    except ValueError as exc:
        raise WebhookVerificationError("CALL-E-Timestamp is not a number.") from exc

    current = time.time() if now is None else now
    if abs(current - sent_at) > TIMESTAMP_WINDOW_SECONDS:
        raise WebhookVerificationError("Webhook timestamp outside the allowed window.")

    try:
        return _webhooks.unwrap(raw_body=raw_body, headers=headers, secret=secret)
    except CalleWebhookSignatureError as exc:
        raise WebhookVerificationError(str(exc)) from exc


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None
