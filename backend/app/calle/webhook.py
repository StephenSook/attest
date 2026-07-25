"""Terminal webhook verification.

Signature scheme (confirmed by reading the calle-ai SDK source, calle/webhooks.py):
HMAC-SHA256 over `timestamp + "." + raw_body` with the webhook secret, sent as
`CALL-E-Signature: v1=<hexdigest>` alongside `CALL-E-Timestamp`.

The SDK verifies the signature but NOT the timestamp window, so replayed
deliveries with a stale timestamp would pass it. This wrapper adds the
five-minute window on top. Verification runs over the exact raw bytes,
before any JSON parsing.
"""

import logging
import math
import os
import time
from collections.abc import Mapping
from typing import Any

from calle.errors import CalleWebhookSignatureError
from calle.webhooks import CalleWebhooks
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app import db as app_db
from app import runs

TIMESTAMP_WINDOW_SECONDS = 300

_webhooks = CalleWebhooks()
logger = logging.getLogger(__name__)

router = APIRouter()


class WebhookVerificationError(Exception):
    pass


@router.post("/calle/webhook", status_code=202)
async def calle_webhook(request: Request, background: BackgroundTasks) -> dict[str, bool]:
    """Terminal result webhook. Raw bytes captured BEFORE any JSON parsing,
    HMAC verified over those exact bytes, 202 returned fast, terminal write
    applied asynchronously. A replayed delivery is a database-level no-op.
    """
    secret = os.environ.get("CALLE_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="webhook verification unavailable")
    raw = await request.body()
    try:
        payload = verify_and_parse_webhook(raw_body=raw, headers=request.headers, secret=secret)
    except WebhookVerificationError as exc:
        logger.warning("webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail="invalid webhook") from None
    background.add_task(runs.apply_terminal_payload, app_db.db_path(), payload)
    return {"received": True}


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
    if not math.isfinite(sent_at):
        raise WebhookVerificationError("CALL-E-Timestamp is not finite.")

    current = time.time() if now is None else now
    if abs(current - sent_at) > TIMESTAMP_WINDOW_SECONDS:
        raise WebhookVerificationError("Webhook timestamp outside the allowed window.")

    try:
        return _webhooks.unwrap(raw_body=raw_body, headers=headers, secret=secret)
    except CalleWebhookSignatureError as exc:
        raise WebhookVerificationError(str(exc)) from exc
    except (ValueError, UnicodeDecodeError) as exc:
        # Valid HMAC over bytes that are not UTF-8 JSON must still be a 400,
        # not an unhandled 500.
        raise WebhookVerificationError("Webhook body is not valid JSON.") from exc


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None
