"""The attestation document: deterministic, publicly verifiable, honest
when unsigned. Verification here uses the PUBLIC key only, exactly as any
judge would."""

import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

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


def _test_key_b64() -> str:
    key = Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)
    del key
    return base64.b64encode(b"\x01" * 32).decode()


async def test_attestation_signed_and_publicly_verifiable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("ATTEST_SIGNING_KEY_ED25519", _test_key_b64())
    _seed(tmp_path / "a.db")
    async with _client() as client:
        doc = (await client.get("/api/runs/run_att/attestation")).json()
        pem = (await client.get("/api/attestation-key")).content
    assert doc["schema"] == "attest/attestation/v1"
    assert doc["signature"]["signed"] is True
    assert doc["signature"]["alg"] == "Ed25519"
    # Verify with the PUBLIC key only, as any judge would.
    signature = doc.pop("signature")
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    public_key = load_pem_public_key(pem)
    public_key.verify(base64.b64decode(signature["value"]), canonical.encode())  # type: ignore[union-attr, call-arg]
    # A tampered document must fail verification.
    tampered = canonical.replace("Example Counseling Center", "Tampered Clinic")
    import pytest as _pytest
    from cryptography.exceptions import InvalidSignature

    with _pytest.raises(InvalidSignature):
        public_key.verify(base64.b64decode(signature["value"]), tampered.encode())  # type: ignore[union-attr, call-arg]
    # The payload hash matches the stored terminal payload bytes.
    assert (
        doc["terminal_payload_sha256"] == hashlib.sha256(json.dumps(FIXTURE).encode()).hexdigest()
    )
    # No phone number anywhere in the document, masked or otherwise.
    assert "+1555" not in json.dumps(doc)


async def test_attestation_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("ATTEST_SIGNING_KEY_ED25519", _test_key_b64())
    _seed(tmp_path / "a.db")
    async with _client() as client:
        first = (await client.get("/api/runs/run_att/attestation")).json()
        second = (await client.get("/api/runs/run_att/attestation")).json()
    assert first == second


async def test_attestation_unsigned_is_honest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.delenv("ATTEST_SIGNING_KEY_ED25519", raising=False)
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


async def test_integral_floats_survive_a_javascript_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Python writes 1.0 where JavaScript writes 1; the served document must
    already be integral-int so a browser's parse-and-restringify verifies."""
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("ATTEST_SIGNING_KEY_ED25519", _test_key_b64())
    _seed(tmp_path / "a.db")
    async with _client() as client:
        raw = (await client.get("/api/runs/run_att/attestation")).text
    assert ".0," not in raw and ".0}" not in raw, (
        "an integral float leaked into the served attestation; "
        "JS re-serialization would break the signature"
    )
