import hashlib
import hmac
import json
import time

import pytest

from app.calle import WebhookVerificationError, verify_and_parse_webhook

SECRET = "test-webhook-secret-not-real"


def _signed(
    payload: dict[str, object], *, timestamp: float | None = None
) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(payload).encode()
    ts = str(timestamp if timestamp is not None else time.time())
    digest = hmac.new(SECRET.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return raw, {"CALL-E-Timestamp": ts, "CALL-E-Signature": f"v1={digest}"}


def test_valid_signature_parses() -> None:
    raw, headers = _signed({"id": "call_1", "status": "completed"})
    parsed = verify_and_parse_webhook(raw_body=raw, headers=headers, secret=SECRET)
    assert parsed["id"] == "call_1"


def test_header_lookup_is_case_insensitive() -> None:
    raw, headers = _signed({"id": "call_1"})
    lowered = {key.lower(): value for key, value in headers.items()}
    parsed = verify_and_parse_webhook(raw_body=raw, headers=lowered, secret=SECRET)
    assert parsed["id"] == "call_1"


def test_tampered_body_is_rejected() -> None:
    raw, headers = _signed({"id": "call_1"})
    with pytest.raises(WebhookVerificationError):
        verify_and_parse_webhook(raw_body=raw + b" ", headers=headers, secret=SECRET)


def test_wrong_secret_is_rejected() -> None:
    raw, headers = _signed({"id": "call_1"})
    with pytest.raises(WebhookVerificationError):
        verify_and_parse_webhook(raw_body=raw, headers=headers, secret="a-different-secret")


def test_stale_timestamp_is_rejected_even_with_valid_signature() -> None:
    stale = time.time() - 3600
    raw, headers = _signed({"id": "call_1"}, timestamp=stale)
    with pytest.raises(WebhookVerificationError):
        verify_and_parse_webhook(raw_body=raw, headers=headers, secret=SECRET)


def test_missing_timestamp_header_is_rejected() -> None:
    raw, headers = _signed({"id": "call_1"})
    del headers["CALL-E-Timestamp"]
    with pytest.raises(WebhookVerificationError):
        verify_and_parse_webhook(raw_body=raw, headers=headers, secret=SECRET)
