"""The attestation document: deterministic, verifiable, honest when unsigned."""

import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest

from app import db, fsm
from app.main import app

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json").read_text()
)


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _seed(database: Path, state: str = "completed") -> None:
    conn = db.connect(database)
    record = {"org": "Example Counseling Center", "replay": True}
    db.create_run(conn, run_id="run_att", idempotency_key="run_att", record_json=json.dumps(record))
    db.set_calle_call_id(conn, "run_att", str(FIXTURE["id"]))
    fsm.advance(conn, "run_att", "submitted")
    if state == "completed":
        fsm.advance(conn, "run_att", "completed", terminal_payload=json.dumps(FIXTURE))
    conn.close()


async def test_attestation_signed_and_verifiable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("ATTEST_SIGNING_KEY", "test-signing-key")
    _seed(tmp_path / "a.db")
    async with _client() as client:
        doc = (await client.get("/api/runs/run_att/attestation")).json()
    assert doc["schema"] == "attest/attestation/v1"
    assert doc["signature"]["signed"] is True
    # Recompute the HMAC exactly as documented: canonical JSON without the
    # signature field.
    signature = doc.pop("signature")
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    expected = hmac.new(b"test-signing-key", canonical.encode(), "sha256").hexdigest()
    assert signature["value"] == expected
    # The payload hash matches the stored terminal payload bytes.
    assert (
        doc["terminal_payload_sha256"] == hashlib.sha256(json.dumps(FIXTURE).encode()).hexdigest()
    )
    # No phone number anywhere in the document, masked or otherwise.
    assert "+1555" not in json.dumps(doc)


async def test_attestation_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("ATTEST_SIGNING_KEY", "k")
    _seed(tmp_path / "a.db")
    async with _client() as client:
        first = (await client.get("/api/runs/run_att/attestation")).json()
        second = (await client.get("/api/runs/run_att/attestation")).json()
    assert first == second


async def test_attestation_unsigned_is_honest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.delenv("ATTEST_SIGNING_KEY", raising=False)
    _seed(tmp_path / "a.db")
    async with _client() as client:
        doc = (await client.get("/api/runs/run_att/attestation")).json()
    assert doc["signature"] == {"alg": None, "signed": False, "value": None}


async def test_attestation_only_for_completed_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "a.db"))
    _seed(tmp_path / "a.db", state="submitted")
    async with _client() as client:
        assert (await client.get("/api/runs/run_att/attestation")).status_code == 409
        assert (await client.get("/api/runs/run_none/attestation")).status_code == 404
