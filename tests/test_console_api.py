"""The console's read API: redaction, analysis, metrics."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app import db, fsm
from app.main import app
from scripts import seed_replay

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json").read_text()
)


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _seed(database: Path) -> None:
    conn = db.connect(database)
    record = {
        "org": "Example Counseling Center",
        "replay": True,
        "published": True,
        "claims": {"accepting_new_patients": "yes", "accepts_plan": "yes"},
    }
    db.create_run(conn, run_id="run_api", idempotency_key="run_api", record_json=json.dumps(record))
    db.set_calle_call_id(conn, "run_api", str(FIXTURE["id"]))
    fsm.advance(conn, "run_api", "submitted")
    fsm.advance(conn, "run_api", "completed", terminal_payload=json.dumps(FIXTURE))
    conn.close()


async def test_runs_list_carries_org_and_replay_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "api.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    _seed(database)
    async with _client() as client:
        response = await client.get("/api/runs")
    assert response.status_code == 200
    runs = response.json()["runs"]
    assert runs[0]["run_id"] == "run_api"
    assert runs[0]["org"] == "Example Counseling Center"
    assert runs[0]["replay"] is True


async def test_run_detail_redacts_phones_and_analyzes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "api2.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    _seed(database)
    conn = db.connect(database)
    try:
        row = db.get_run(conn, "run_api")
        assert row is not None
        payload = json.loads(str(row["terminal_payload"]))
        payload["+15550101234"] = "root-key"
        payload["results"] = {
            "+15550101234": "nested-key",
            "acct15550101234": "embedded-key",
            "2099-12-31": "generic-date",
        }
        payload["recipientIDS"] = ["call_x15550101234aaaaaaaaa"]
        payload["RECIPIENTIDS"] = {"2099-12-31": "acctB15550101234C"}
        payload["metadata"]["unknown_number"] = 15550101234
        payload["metadata"]["items"] = [15550101234.0]
        payload["recipients"][0]["attempts"][0]["transcript_turns"][6]["text"] = (
            "Yep. Call +15550101234."
        )
        conn.execute(
            "UPDATE call_runs SET terminal_payload = ? WHERE run_id = ?",
            (json.dumps(payload), "run_api"),
        )
        conn.commit()
    finally:
        conn.close()
    async with _client() as client:
        response = await client.get("/api/runs/run_api")
    assert response.status_code == 200
    body = response.json()
    raw = json.dumps(body)
    assert "+15550101234" not in raw, "unmasked phone leaked through the API"
    assert "acct15550101234" not in raw
    assert "acctB15550101234C" not in raw
    assert "call_x15550101234aaaaaaaaa" not in raw
    assert "15550101234" not in raw
    assert body["payload"]["results"]["2099-12-31"] == "generic-date"
    assert "+15*" in raw
    claims = {c["claim"]: c for c in body["analysis"]["claims"]}
    assert claims["accepting_new_patients"]["answer"] == "yes"
    assert claims["accepting_new_patients"]["span"]["text"] == "Yep. Call [redacted phone]."
    assert claims["accepts_plan"]["abstain"] is True
    recon = body["analysis"]["reconciliation"]
    assert recon["verdict"] in {"verified", "unverifiable", "contradicted"}
    assert any(c["agreed"] is True for c in recon["contributions"])


async def test_failed_run_details_redact_error_text_on_public_and_private_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "failed-details.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    token = "private-run-capability-token"
    conn = db.connect(database)
    try:
        records = {
            "run_public_failure": {"org": "Public failure", "published": True},
            "run_private_failure": {
                "org": "Private failure",
                "published": False,
                "access_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            },
        }
        for run_id, record in records.items():
            db.create_run(
                conn,
                run_id=run_id,
                idempotency_key=run_id,
                record_json=json.dumps(record),
            )
            fsm.advance(
                conn,
                run_id,
                "failed",
                terminal_payload=json.dumps(
                    {"status": "failed", "error": "Could not call +15550101234", "stage": "poll"}
                ),
            )
        stored_payloads = [
            str(row["terminal_payload"])
            for row in conn.execute("SELECT terminal_payload FROM call_runs")
        ]
        assert all("+15550101234" not in payload for payload in stored_payloads)
    finally:
        conn.close()

    async with _client() as client:
        public = await client.get("/api/runs/run_public_failure")
        private = await client.get(
            "/internal/runs/run_private_failure",
            headers={"X-Attest-Run-Token": token},
        )

    for response in [public, private]:
        assert response.status_code == 200
        body = response.json()
        assert "+15550101234" not in json.dumps(body)
        assert body["payload"]["error"] == "Could not call [redacted phone]"
        assert body["failure"]["error"] == "Could not call [redacted phone]"


async def test_provider_ids_survive_persistence_and_both_detail_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "provider-ids.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    token = "private-provider-id-token"
    expected_recipient_id = "rcp_1234567890abcdef"
    expected_attempt_id = "att_1234567890abcdef"
    expected_provider_call_id = "1234567890abcdef1234567890abcdef"
    runs = {
        "run_public_ids": {
            "published": True,
            "call_id": "call_1234567890abcdefghijkl",
        },
        "run_private_ids": {
            "published": False,
            "call_id": "call_1234567890abcdefghijkm",
            "access_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        },
    }

    conn = db.connect(database)
    try:
        for run_id, values in runs.items():
            payload = json.loads(json.dumps(FIXTURE))
            payload["id"] = values["call_id"]
            payload["recipients"][0]["id"] = expected_recipient_id
            attempt = payload["recipients"][0]["attempts"][0]
            attempt["id"] = expected_attempt_id
            attempt["provider_call_id"] = expected_provider_call_id
            record = {
                "org": run_id,
                "published": values["published"],
                "access_token_sha256": values.get("access_token_sha256"),
            }
            db.create_run(
                conn,
                run_id=run_id,
                idempotency_key=run_id,
                record_json=json.dumps(record),
            )
            db.set_calle_call_id(conn, run_id, str(values["call_id"]))
            fsm.advance(conn, run_id, "submitted")
            fsm.advance(conn, run_id, "completed", terminal_payload=json.dumps(payload))
            stored = db.get_run(conn, run_id)
            assert stored is not None
            stored_payload = json.loads(str(stored["terminal_payload"]))
            stored_attempt = stored_payload["recipients"][0]["attempts"][0]
            assert stored_payload["id"] == values["call_id"]
            assert stored_payload["recipients"][0]["id"] == expected_recipient_id
            assert stored_attempt["id"] == expected_attempt_id
            assert stored_attempt["provider_call_id"] == expected_provider_call_id
    finally:
        conn.close()

    async with _client() as client:
        public = await client.get("/api/runs/run_public_ids")
        private = await client.get(
            "/internal/runs/run_private_ids",
            headers={"X-Attest-Run-Token": token},
        )

    for response in [public, private]:
        assert response.status_code == 200
        payload = response.json()["payload"]
        attempt = payload["recipients"][0]["attempts"][0]
        assert payload["recipients"][0]["id"] == expected_recipient_id
        assert attempt["id"] == expected_attempt_id
        assert attempt["provider_call_id"] == expected_provider_call_id


async def test_metrics_endpoint_serves_eval_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps({"seed": 20260725, "headline": {"alpha": 0.1}}))
    monkeypatch.setenv("ATTEST_METRICS_PATH", str(metrics))
    async with _client() as client:
        response = await client.get("/api/metrics")
    assert response.status_code == 200
    assert response.json()["seed"] == 20260725


async def test_unknown_run_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "api3.db"))
    async with _client() as client:
        response = await client.get("/api/runs/run_missing")
    assert response.status_code == 404


def test_seed_script_is_idempotent(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin:/bin", "ATTEST_DB_PATH": str(tmp_path / "seed.db")}
    root = Path(__file__).parent.parent
    first = subprocess.run(
        [sys.executable, "scripts/seed_replay.py"],
        capture_output=True,
        text=True,
        env=env,
        cwd=root,
        check=True,
    )
    second = subprocess.run(
        [sys.executable, "scripts/seed_replay.py"],
        capture_output=True,
        text=True,
        env=env,
        cwd=root,
        check=True,
    )
    assert "seeded" in first.stdout
    assert "nothing to do" in second.stdout


_DEMO_DESK_RUN = "run_replay_demo_desk_0001"
_PLACEHOLDER_DIGITS = "15550101234"


def test_replay_fixtures_carry_only_the_reserved_placeholder_number() -> None:
    """Every seeded replay is a scrubbed real payload. The only digit run long
    enough to be a phone number must be the reserved placeholder, nothing may
    survive platform-side masking, and no em-dash may enter the tree."""
    for replay in seed_replay.REPLAYS:
        raw = (seed_replay.FIXTURES / replay.fixture).read_text()
        assert json.loads(raw)["id"], replay.fixture
        assert set(re.findall(r"[0-9]{10,}", raw)) == {_PLACEHOLDER_DIGITS}, replay.fixture
        assert chr(0x2014) not in raw, replay.fixture
        assert "***" not in raw, replay.fixture


async def test_demo_desk_replay_is_served_as_the_film_shows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The film's evidence beat shows demo take 3 landing CONTRADICTED with
    three cited spans. The deployed console seeds from REPLAYS on boot, so
    that run must be seeded, published, labeled a replay, and served with the
    placeholder masked."""
    replays = {item.run_id: item for item in seed_replay.REPLAYS}
    assert _DEMO_DESK_RUN in replays, "the demo desk replay is not in REPLAYS"
    fixture = json.loads((seed_replay.FIXTURES / replays[_DEMO_DESK_RUN].fixture).read_text())
    assert fixture["id"] == "call_replay_demo_desk_0001"
    assert fixture["recipients"][0]["phones"] == ["+15550101234"]
    assert fixture["recipients"][0]["attempts"][0]["phone"] == "+15550101234"

    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "demo-desk.db"))
    monkeypatch.setenv("ATTEST_AUDIO_DIR", str(tmp_path / "audio"))
    seed_replay.main()

    async with _client() as client:
        ledger = await client.get("/api/runs")
        detail = await client.get(f"/api/runs/{_DEMO_DESK_RUN}")

    rows = {item["run_id"]: item for item in ledger.json()["runs"]}
    assert rows[_DEMO_DESK_RUN]["org"] == "Attest Demo Desk"
    assert rows[_DEMO_DESK_RUN]["replay"] is True
    assert rows[_DEMO_DESK_RUN]["verdict"] == "contradicted"

    assert detail.status_code == 200
    body = detail.json()
    assert body["state"] == "completed"
    assert body["published"] is True
    assert body["provider"] == "live"
    assert body["has_audio"] is False
    analysis = body["analysis"]
    assert analysis["org"] == "Attest Demo Desk"
    assert analysis["replay"] is True
    assert analysis["reconciliation"]["verdict"] == "contradicted"
    assert analysis["reconciliation"]["posterior_probability"] == pytest.approx(0.0888, abs=0.0005)
    claims = {item["claim"]: item for item in analysis["claims"]}
    assert set(claims) == {"office_name_confirmed", "accepting_new_patients", "accepts_plan"}
    assert claims["office_name_confirmed"]["answer"] == "yes"
    assert claims["accepting_new_patients"]["answer"] == "no"
    assert claims["accepts_plan"]["answer"] == "no"
    for item in claims.values():
        assert item["span"] is not None and item["span"]["text"], item["claim"]

    assert body["payload"]["recipients"][0]["phones"] == ["+15******234"]
    assert _PLACEHOLDER_DIGITS not in detail.text
    assert _PLACEHOLDER_DIGITS not in ledger.text
