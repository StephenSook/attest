"""The console's read API: redaction, analysis, metrics."""

import json
import subprocess
import sys
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


def _seed(database: Path) -> None:
    conn = db.connect(database)
    record = {
        "org": "Example Counseling Center",
        "replay": True,
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
    async with _client() as client:
        response = await client.get("/api/runs/run_api")
    assert response.status_code == 200
    body = response.json()
    raw = json.dumps(body)
    assert "+15550101234" not in raw, "unmasked phone leaked through the API"
    assert "+15*" in raw
    claims = {c["claim"]: c for c in body["analysis"]["claims"]}
    assert claims["accepting_new_patients"]["answer"] == "yes"
    assert claims["accepting_new_patients"]["span"]["text"] == "Yep."
    assert claims["accepts_plan"]["abstain"] is True
    recon = body["analysis"]["reconciliation"]
    assert recon["verdict"] in {"verified", "unverifiable", "contradicted"}
    assert any(c["agreed"] is True for c in recon["contributions"])


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
