"""Terminal webhook receiver, two modes, chosen by whether a secret exists.

Platform history, because it decides the trust model: when this receiver was
built (July 25), webhook_url was accepted and nothing was ever delivered, and
the documented contract was HMAC-SHA256 over `timestamp + "." + raw_body`
(`CALL-E-Signature: v1=<hexdigest>` plus `CALL-E-Timestamp`). The platform
changelog dated 2026-07-29 changed both facts at once: delivery is now live,
and it is UNSIGNED, with only a `CALL-E-Event-Id` header for deduplication.
SDK 0.6.0 deprecates its `verify`/`unwrap` helpers for exactly that reason.

So the two modes are:

- CALLE_WEBHOOK_SECRET set (the mock server and any compatible signing layer):
  the original contract. Raw bytes captured BEFORE any JSON parsing, HMAC
  verified over those exact bytes, plus the five-minute freshness window the
  SDK's verifier omits. The verified payload is applied directly.

- No secret (the live platform today): HINT MODE. An unsigned delivery proves
  nothing about its sender, so nothing in the body is ever written. The body
  is used for exactly one thing: extracting a call id. If that id names a run
  we own that is still in flight, an authoritative `GET /v1/calls/{call_id}`
  is fetched with our API key and THAT snapshot is applied, which is also the
  integrity pattern the platform docs themselves recommend. A hint for an
  unknown or already-terminal call is accepted and dropped, indistinguishably,
  so the endpoint does not confirm which call ids exist.

Amplification is bounded: a forged hint triggers at most one authenticated GET
to CALL-E, and only when it names one of our own runs that is currently in
flight, which requires knowing an unguessable live call id. The poller remains
authoritative either way; a lost or dropped hint delays nothing forever.
"""

import json
import logging
import math
import os
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from calle.errors import CalleWebhookSignatureError
from calle.webhooks import CalleWebhooks
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app import db as app_db
from app import fsm, runs
from app.calle.client import CalleService

TIMESTAMP_WINDOW_SECONDS = 300
# Terminal snapshots carry full transcripts; tens of kilobytes in practice.
# Anything past this is not a plausible delivery and is dropped unread.
MAX_HINT_BODY_BYTES = 256 * 1024
_CALL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

_webhooks = CalleWebhooks()
logger = logging.getLogger(__name__)

router = APIRouter()


class WebhookVerificationError(Exception):
    pass


@router.post("/calle/webhook", status_code=202)
async def calle_webhook(request: Request, background: BackgroundTasks) -> dict[str, bool]:
    """Terminal result webhook. 202 fast, work applied asynchronously.

    With a secret configured the payload is HMAC-verified over the raw bytes
    and applied directly; without one it is an untrusted hint that at most
    triggers an authoritative re-fetch. A replayed delivery is a no-op in
    both modes, at the database layer.
    """
    secret = os.environ.get("CALLE_WEBHOOK_SECRET", "")
    raw = await request.body()

    if secret:
        try:
            payload = verify_and_parse_webhook(raw_body=raw, headers=request.headers, secret=secret)
        except WebhookVerificationError as exc:
            logger.warning("webhook rejected: %s", exc)
            raise HTTPException(status_code=400, detail="invalid webhook") from None
        background.add_task(runs.apply_terminal_payload, app_db.db_path(), payload)
        return {"received": True}

    # Hint mode. The platform sends CALL-E-Event-Id on every delivery; its
    # absence marks traffic that is not a delivery at all.
    if _header(request.headers, "CALL-E-Event-Id") is None:
        raise HTTPException(status_code=400, detail="missing CALL-E-Event-Id")
    if len(raw) > MAX_HINT_BODY_BYTES:
        raise HTTPException(status_code=400, detail="body too large")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="body is not JSON") from None

    call_id = _call_id_from_hint(payload)
    if call_id is not None:
        background.add_task(_follow_hint, app_db.db_path(), call_id)
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


def _call_id_from_hint(payload: object) -> str | None:
    """Extract a plausible call id from an untrusted delivery, nothing more.

    The documented event wraps the terminal snapshot under `data`, so
    `data.id` is preferred; a bare snapshot's `id` is accepted for
    compatibility. A wrong or forged value is harmless by construction: it
    either matches no run of ours or triggers one authoritative re-fetch.
    """
    if not isinstance(payload, dict):
        return None
    candidates: list[object] = []
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.extend([data.get("id"), data.get("call_id")])
    candidates.extend([payload.get("call_id"), payload.get("id")])
    for candidate in candidates:
        if isinstance(candidate, str) and _CALL_ID_PATTERN.fullmatch(candidate):
            return candidate
    return None


async def _fetch_authoritative(call_id: str) -> dict[str, Any]:
    """One authenticated GET /v1/calls/{call_id}. Module-level so tests can
    replace it without a network."""
    service = CalleService()
    try:
        return await service.get_call(call_id)
    finally:
        service.close()


async def _follow_hint(database: Path, calle_call_id: str) -> None:
    """The only thing an unsigned delivery is allowed to cause.

    Look the id up among OUR runs; if it is in flight, fetch the authoritative
    snapshot with our API key and apply that. The hint body itself is never
    written, so a forged delivery cannot plant a result.
    """
    conn = app_db.connect(database)
    try:
        row = app_db.get_run_by_calle_call_id(conn, calle_call_id)
    finally:
        conn.close()
    if row is None or str(row["state"]) in fsm.TERMINAL_STATES:
        return
    try:
        snapshot = await _fetch_authoritative(calle_call_id)
    except Exception:
        # The poller retries on its own schedule; a failed hint costs nothing.
        logger.warning("hint re-fetch failed for call %s", calle_call_id, exc_info=True)
        return
    runs.apply_terminal_payload(database, snapshot)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None
