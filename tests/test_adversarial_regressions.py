"""Regression pins for the second-model adversarial review findings (PR #4)."""

import hashlib
import hmac
import json
import time
from pathlib import Path

import pytest
import respx

from app import db, runs
from app.calle import WebhookVerificationError, verify_and_parse_webhook
from app.calle.client import CalleService
from app.security import ssrf

SECRET = "regression-secret-not-real"


def _sign(raw: bytes, ts: str) -> dict[str, str]:
    digest = hmac.new(SECRET.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return {"CALL-E-Timestamp": ts, "CALL-E-Signature": f"v1={digest}"}


def test_nan_timestamp_rejected_even_with_valid_signature() -> None:
    raw = json.dumps({"id": "call_1"}).encode()
    headers = _sign(raw, "nan")
    with pytest.raises(WebhookVerificationError):
        verify_and_parse_webhook(raw_body=raw, headers=headers, secret=SECRET)


def test_valid_hmac_over_non_json_bytes_is_verification_error_not_500() -> None:
    raw = b"\xff\xfe not json"
    headers = _sign(raw, str(time.time()))
    with pytest.raises(WebhookVerificationError):
        verify_and_parse_webhook(raw_body=raw, headers=headers, secret=SECRET)


@pytest.mark.parametrize(
    "url",
    [
        "https://[::1/x",  # malformed bracket -> SSRFError, not ValueError
        "https://example.com:99999/x",  # out-of-range port
        "http://192.0.0.9/x",  # special-use, python says is_global
        "http://192.0.0.10/x",
        "http://100.100.100.200/x",
        "http://[::ffff:127.0.0.1]/x",  # IPv4-mapped IPv6 loopback
        "http://[::ffff:10.0.0.1]/x",
    ],
)
def test_adversarial_ssrf_bypass_attempts_blocked(url: str) -> None:
    with pytest.raises(ssrf.SSRFError):
        ssrf.resolve_and_validate(url)


@respx.mock
async def test_ambiguous_submit_recorded_distinctly(tmp_path: Path) -> None:
    import httpx as _httpx

    database = tmp_path / "ambig.db"
    respx.post("https://calle.test/v1/calls").mock(side_effect=_httpx.ConnectError("boom"))
    service = CalleService(api_key="k", base_url="https://calle.test")
    with pytest.raises(Exception):  # noqa: B017 - the seam wraps transport errors
        await runs.start_verification_run(service, database, task="verify", phone="+15550101234")
    conn = db.connect(database)
    rows = list(conn.execute("SELECT state, terminal_payload FROM call_runs"))
    assert len(rows) == 1
    assert rows[0]["state"] == "failed"
    assert "submit_ambiguous" in str(rows[0]["terminal_payload"])
    conn.close()
    service.close()
