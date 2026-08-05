import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pytest

from app import db, fsm
from app.main import app

SECRET = "endpoint-secret-not-real"
FIXTURE = json.loads(
    (Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json").read_text()
)


def _signed_headers(raw: bytes) -> dict[str, str]:
    ts = str(time.time())
    digest = hmac.new(SECRET.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return {"CALL-E-Timestamp": ts, "CALL-E-Signature": f"v1={digest}"}


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _seed_run(database: Path) -> None:
    conn = db.connect(database)
    db.create_run(conn, run_id="run_wh", idempotency_key="run_wh")
    db.set_calle_call_id(conn, "run_wh", str(FIXTURE["id"]))
    fsm.advance(conn, "run_wh", "submitted")
    conn.close()


async def test_valid_webhook_lands_terminal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "wh.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.setenv("CALLE_WEBHOOK_SECRET", SECRET)
    _seed_run(database)

    raw = json.dumps(FIXTURE).encode()
    async with _client() as client:
        response = await client.post("/calle/webhook", content=raw, headers=_signed_headers(raw))
    assert response.status_code == 202

    conn = db.connect(database)
    row = db.get_run(conn, "run_wh")
    assert row is not None and row["state"] == "completed"
    conn.close()


async def test_replayed_webhook_is_a_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "wh2.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.setenv("CALLE_WEBHOOK_SECRET", SECRET)
    _seed_run(database)

    raw = json.dumps(FIXTURE).encode()
    headers = _signed_headers(raw)
    async with _client() as client:
        first = await client.post("/calle/webhook", content=raw, headers=headers)
        second = await client.post("/calle/webhook", content=raw, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 202

    conn = db.connect(database)
    row = db.get_run(conn, "run_wh")
    assert row is not None and row["state"] == "completed"
    conn.close()


async def test_bad_signature_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "wh3.db"))
    monkeypatch.setenv("CALLE_WEBHOOK_SECRET", SECRET)
    raw = json.dumps(FIXTURE).encode()
    headers = _signed_headers(raw)
    headers["CALL-E-Signature"] = "v1=" + "0" * 64
    async with _client() as client:
        response = await client.post("/calle/webhook", content=raw, headers=headers)
    assert response.status_code == 400


# Hint mode: the platform's deliveries went live UNSIGNED on 2026-07-29, so
# with no secret configured the receiver treats a delivery as an untrusted
# wake-up signal. The tests below pin the two properties that make that safe:
# the body is never written, and only a known in-flight run triggers a fetch.


def _hint_fetcher(monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, object]) -> list[str]:
    """Replace the authoritative re-fetch with a recorder returning snapshot.

    Also clears the module's per-call-id cooldown map, which is process state
    and would otherwise let one test's hint suppress the next test's fetch,
    making a guard assertion pass for the wrong reason.
    """
    from app.calle import webhook as webhook_module

    webhook_module._recent_hints.clear()
    fetched: list[str] = []

    async def fake_fetch(call_id: str) -> dict[str, object]:
        fetched.append(call_id)
        return snapshot

    monkeypatch.setattr(webhook_module, "_fetch_authoritative", fake_fetch)
    return fetched


async def test_unsigned_hint_applies_the_fetched_snapshot_not_the_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hint LIES (status failed); the authoritative snapshot says
    completed. The run must end completed, proving the body was never
    trusted and the fetch was."""
    database = tmp_path / "wh4.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.delenv("CALLE_WEBHOOK_SECRET", raising=False)
    _seed_run(database)
    fetched = _hint_fetcher(monkeypatch, FIXTURE)

    lying_hint = {
        "type": "call.completed",
        "id": "evt_not_a_call_id_1",
        "data": {**FIXTURE, "status": "failed", "evidence": ["planted by an attacker"]},
    }
    async with _client() as client:
        response = await client.post(
            "/calle/webhook",
            content=json.dumps(lying_hint).encode(),
            headers={"CALL-E-Event-Id": "evt_1"},
        )
    assert response.status_code == 202
    assert fetched == [str(FIXTURE["id"])]

    conn = db.connect(database)
    row = db.get_run(conn, "run_wh")
    assert row is not None and row["state"] == "completed"
    payload = json.loads(row["terminal_payload"])
    assert payload["status"] == "completed"
    assert "planted by an attacker" not in json.dumps(payload)
    conn.close()


async def test_unsigned_hint_for_unknown_call_id_is_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "wh5.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.delenv("CALLE_WEBHOOK_SECRET", raising=False)
    _seed_run(database)
    fetched = _hint_fetcher(monkeypatch, FIXTURE)

    hint = {"type": "call.completed", "data": {"id": "call_someone_elses_0001"}}
    async with _client() as client:
        response = await client.post(
            "/calle/webhook",
            content=json.dumps(hint).encode(),
            headers={"CALL-E-Event-Id": "evt_2"},
        )
    assert response.status_code == 202, "unknown ids must not be distinguishable"
    assert fetched == [], "an unknown call id must not trigger a fetch"

    conn = db.connect(database)
    row = db.get_run(conn, "run_wh")
    assert row is not None and row["state"] == "submitted"
    conn.close()


async def test_unsigned_hint_for_terminal_run_does_not_refetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "wh6.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.delenv("CALLE_WEBHOOK_SECRET", raising=False)
    _seed_run(database)
    conn = db.connect(database)
    fsm.advance(conn, "run_wh", "completed", terminal_payload=json.dumps(FIXTURE))
    conn.close()
    fetched = _hint_fetcher(monkeypatch, FIXTURE)

    hint = {"type": "call.completed", "data": {"id": str(FIXTURE["id"])}}
    async with _client() as client:
        response = await client.post(
            "/calle/webhook",
            content=json.dumps(hint).encode(),
            headers={"CALL-E-Event-Id": "evt_3"},
        )
    assert response.status_code == 202
    assert fetched == [], "a replayed hint for a terminal run must be a no-op"


async def test_unsigned_hint_without_event_id_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "wh7.db"))
    monkeypatch.delenv("CALLE_WEBHOOK_SECRET", raising=False)
    async with _client() as client:
        response = await client.post("/calle/webhook", content=json.dumps(FIXTURE).encode())
    assert response.status_code == 400


async def test_unsigned_hint_with_malformed_body_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "wh8.db"))
    monkeypatch.delenv("CALLE_WEBHOOK_SECRET", raising=False)
    async with _client() as client:
        not_json = await client.post(
            "/calle/webhook", content=b"\xff\xfenope", headers={"CALL-E-Event-Id": "evt_4"}
        )
        oversized = await client.post(
            "/calle/webhook",
            content=b"[" + b" " * (256 * 1024 + 1),
            headers={"CALL-E-Event-Id": "evt_5"},
        )
    assert not_json.status_code == 400
    assert oversized.status_code == 413


async def test_unsigned_hint_cooldown_bounds_refetches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replaying one captured delivery must not multiply outbound fetches.

    The fake fetch returns a NON-terminal snapshot so the run stays in
    flight; the second hint is then blocked by the cooldown alone, which is
    the property under test."""
    database = tmp_path / "wh9.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.delenv("CALLE_WEBHOOK_SECRET", raising=False)
    _seed_run(database)
    fetched = _hint_fetcher(monkeypatch, {**FIXTURE, "status": "in_progress"})

    hint = json.dumps({"type": "call.completed", "data": {"id": str(FIXTURE["id"])}}).encode()
    async with _client() as client:
        first = await client.post(
            "/calle/webhook", content=hint, headers={"CALL-E-Event-Id": "evt_6"}
        )
        second = await client.post(
            "/calle/webhook", content=hint, headers={"CALL-E-Event-Id": "evt_7"}
        )
    assert first.status_code == 202
    assert second.status_code == 202, "a rate-limited hint must not be distinguishable"
    assert fetched == [str(FIXTURE["id"])], "the cooldown must hold the second fetch"


async def test_empty_string_secret_means_hint_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CALLE_WEBHOOK_SECRET="" must select hint mode, not an HMAC check
    against an empty key that nothing could ever legitimately sign with."""
    database = tmp_path / "wh10.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.setenv("CALLE_WEBHOOK_SECRET", "")
    _seed_run(database)
    fetched = _hint_fetcher(monkeypatch, FIXTURE)

    hint = json.dumps({"type": "call.completed", "data": {"id": str(FIXTURE["id"])}}).encode()
    async with _client() as client:
        response = await client.post(
            "/calle/webhook", content=hint, headers={"CALL-E-Event-Id": "evt_8"}
        )
    assert response.status_code == 202
    assert fetched == [str(FIXTURE["id"])]
