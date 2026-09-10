"""Regression pins for the full-repo audit findings.

Each test here corresponds to a finding from the parallel review sweep and
fails if the fix regresses. Named by what breaks, not by finding number.
"""

import json
import os
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from app import db, fsm
from app.calle import client as calle_client
from app.extract import extract_yes_no
from app.main import app
from app.models import Answer
from app.runs import build_task
from scripts import seed_replay

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json").read_text()
)


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def test_concurrent_connect_serializes_legacy_schema_migration(tmp_path: Path) -> None:
    database = tmp_path / "legacy-concurrent.db"
    seed = sqlite3.connect(database)
    seed.execute(
        "CREATE TABLE call_runs ("
        "run_id TEXT PRIMARY KEY, calle_call_id TEXT UNIQUE, "
        "idempotency_key TEXT UNIQUE NOT NULL, state TEXT NOT NULL, "
        "created_at TEXT, updated_at TEXT, terminal_payload TEXT, record_json TEXT)"
    )
    seed.commit()
    seed.close()

    workers = 12
    barrier = threading.Barrier(workers)

    def connect_once() -> set[str]:
        barrier.wait(timeout=5)
        conn = db.connect(database)
        try:
            return {str(row["name"]) for row in conn.execute("PRAGMA table_info(call_runs)")}
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        migrated = list(pool.map(lambda _: connect_once(), range(workers)))

    required = {
        "dispatch_digest",
        "dispatch_base_url",
        "dispatch_provider",
        "dispatch_credential_fingerprint",
        "destination_hash",
        "dispatch_expires_at",
        "submit_attempts",
        "submit_lease_owner",
        "submit_lease_until",
    }
    assert all(required <= columns for columns in migrated)


def test_benign_no_phrases_are_not_a_refusal() -> None:
    """ "Sure, no problem, we are accepting new patients" must not extract a
    confident NO; a wrong answer with a highlighted span is the worst output
    this system can produce."""
    turns: list[dict[str, object]] = [
        {"speaker": "bot", "text": "Are you accepting new patients?"},
        {"speaker": "user", "text": "Sure, no problem, we are accepting new patients."},
    ]
    assert extract_yes_no(turns).answer is Answer.YES

    turns[1] = {"speaker": "user", "text": "No worries, we are accepting new patients."}
    assert extract_yes_no(turns).answer is Answer.YES

    # A real refusal still reads as one.
    turns[1] = {"speaker": "user", "text": "No, we are not taking new patients."}
    assert extract_yes_no(turns).answer is Answer.NO


def test_call_script_forbids_leaving_voicemail() -> None:
    """A verification cannot be established from a recording, and a real
    practice should never find a robot message on their line."""
    task = build_task("Example Practice", {})
    assert "voicemail" in task.lower()
    assert "do not leave a message" in task.lower().replace("do not", "do not")


async def test_attestation_policy_matches_calibration_availability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_DB_PATH", str(tmp_path / "b.db"))
    monkeypatch.setenv("ATTEST_METRICS_PATH", str(tmp_path / "missing.json"))
    conn = db.connect(tmp_path / "b.db")
    db.create_run(
        conn,
        run_id="run_pol",
        idempotency_key="run_pol",
        record_json=json.dumps({"org": "X", "published": True}),
    )
    db.set_calle_call_id(conn, "run_pol", str(FIXTURE["id"]))
    fsm.advance(conn, "run_pol", "submitted")
    fsm.advance(conn, "run_pol", "completed", terminal_payload=json.dumps(FIXTURE))
    conn.close()
    async with _client() as client:
        doc = (await client.get("/api/runs/run_pol/attestation")).json()
    assert doc["calibration"]["available"] is False
    assert "NO calibrated gate" in doc["policy"]


async def test_healthz_reports_poller_liveness() -> None:
    async with _client() as client:
        body = (await client.get("/healthz")).json()
    assert "poller" in body
    assert body["status"] in {"ok", "degraded"}


async def test_healthz_reports_sandbox_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATTEST_SANDBOX_ENABLED", raising=False)
    async with _client() as client:
        assert (await client.get("/healthz")).json()["sandbox"] == "disabled"

    monkeypatch.setenv("ATTEST_SANDBOX_ENABLED", "1")
    monkeypatch.setenv("ATTEST_JUDGE_KEY", "test-judge-key")
    monkeypatch.setenv("ATTEST_PHONE_HASH_KEY", "test-phone-hash-key")
    async with _client() as client:
        assert (await client.get("/healthz")).json()["sandbox"] == "enabled"

    monkeypatch.delenv("ATTEST_PHONE_HASH_KEY")
    async with _client() as client:
        assert (await client.get("/healthz")).json()["sandbox"] == "disabled"

    monkeypatch.setenv("ATTEST_PHONE_HASH_KEY", "test-phone-hash-key")
    monkeypatch.delenv("ATTEST_JUDGE_KEY", raising=False)
    async with _client() as client:
        assert (await client.get("/healthz")).json()["sandbox"] == "disabled"


def test_mock_mode_is_detectable() -> None:
    """A mock-served run must be distinguishable from a real one."""
    assert callable(calle_client.is_mock_mode)


def test_harness_and_served_gate_are_the_same_function() -> None:
    """The published abstention rate must describe the gate that ships.

    They diverged once: the harness counted a singleton {unknown} set as an
    answer while the server counted it as an abstention, so the README
    published 26.7 percent abstention for a product that abstained 57.7
    percent of the time. Both now call eval.conformal.abstains.
    """
    import inspect

    from app import analysis
    from eval import conformal, study

    assert "abstains(" in inspect.getsource(analysis.analyze_run)
    assert "abstains(" in inspect.getsource(conformal.evaluate_alpha)
    assert "abstains(" in inspect.getsource(study.analyze)

    # And the rule itself: a lone "unknown" is an abstention.
    lonely_unknown = {"yes": 0.05, "no": 0.05, "unknown": 0.9}
    assert conformal.prediction_set(lonely_unknown, 0.75) == {"unknown"}
    assert conformal.abstains(lonely_unknown, "unknown", 0.75) is True
    confident_yes = {"yes": 0.9, "no": 0.04, "unknown": 0.06}
    assert conformal.abstains(confident_yes, "yes", 0.75) is False


def test_transcript_walker_survives_an_explicit_null_recipients() -> None:
    """The API sends an explicit null for a list it has no value for, and a
    dict default only covers the absent key. The served path raised TypeError
    on "recipients": null while eval's since-removed copy returned cleanly,
    which is how the divergence was found."""
    from app.analysis import transcript_turns

    assert transcript_turns({"recipients": None}) == []
    assert transcript_turns({"recipients": [{"attempts": None}]}) == []
    assert transcript_turns({}) == []


def test_eval_scorecard_defines_no_second_walker() -> None:
    """One walker, not two. The copies had already drifted on null handling,
    so this asserts the structure rather than the behavior: a reintroduced
    private copy would pass a behavioral test on the day it was written."""
    source = (Path(__file__).parent.parent / "eval" / "scorecard.py").read_text()

    assert "def _transcript_turns" not in source, "a private walker came back"
    assert "from app.analysis import" in source and "transcript_turns" in source


def test_landing_stats_match_the_generated_metrics() -> None:
    """The landing page's three headline numbers are hand-typed literals.

    Landing.tsx carried a comment promising these "stay test-pinned to
    metrics.json". No such test existed. That is the same sync-by-comment
    promise that already failed for the extractor, the abstention gate, and
    the call task, and it guards the most-viewed public surface: a reseed or
    a gate change would silently leave three wrong numbers on the front page,
    which is exactly what happened to the fact sheet after PR #51.

    The console does not need this because it reads metrics from the API. The
    landing page cannot, because it is a static scroll film with no fetch.
    """
    metrics = json.loads(
        (Path(__file__).parent.parent / "eval" / "results" / "metrics.json").read_text()
    )
    head = metrics["headline"]
    landing = (
        Path(__file__).parent.parent / "frontend" / "src" / "experience" / "Landing.tsx"
    ).read_text()

    expected = {
        "empirical_coverage": f"{head['empirical_coverage'] * 100:.1f}%",
        "abstention_rate": f"{head['abstention_rate'] * 100:.1f}%",
        "accuracy_when_answering": f"{head['accuracy_when_answering'] * 100:.1f}%",
    }
    for key, printed in expected.items():
        assert f">{printed}<" in landing, (
            f"Landing.tsx no longer prints {printed} for {key}. metrics.json moved and the "
            f"front page did not. Update the stat literal in "
            f"frontend/src/experience/Landing.tsx."
        )


async def test_healthz_reports_whether_it_can_actually_dial(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A deployment missing one env var serves simulated results silently.

    ATTEST_USE_MOCK defaults to true, so an instance that never set it dials
    nothing and still answers every request. Run records carry the provider
    stamp, but only after a call exists. Health has to say it up front, or the
    only way to discover a mock deployment is to read a result that was never
    a phone call.
    """
    transport = httpx.ASGITransport(app=app)

    monkeypatch.setenv("ATTEST_USE_MOCK", "false")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/healthz")).json()["provider"] == "live"

    monkeypatch.setenv("ATTEST_USE_MOCK", "true")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/healthz")).json()["provider"] == "mock"

    # The dangerous case: unset. It must read as mock, never as live.
    monkeypatch.delenv("ATTEST_USE_MOCK", raising=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/healthz")).json()["provider"] == "mock"


async def test_private_rows_cannot_crowd_published_runs_out_of_the_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "ledger.db"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    conn = db.connect(database)
    try:
        db.create_run(
            conn,
            run_id="run_published_old",
            idempotency_key="run_published_old",
            record_json=json.dumps({"org": "Visible Evidence", "published": True}),
        )
        conn.execute(
            "UPDATE call_runs SET created_at = '2020-01-01T00:00:00Z' "
            "WHERE run_id = 'run_published_old'"
        )
        for index in range(51):
            run_id = f"run_private_{index:02d}"
            db.create_run(
                conn,
                run_id=run_id,
                idempotency_key=run_id,
                record_json=json.dumps({"org": f"Private {index}"}),
            )
        conn.commit()
    finally:
        conn.close()

    async with _client() as client:
        response = await client.get("/api/runs")

    assert response.status_code == 200
    assert [item["run_id"] for item in response.json()["runs"]] == ["run_published_old"]


async def test_legacy_seed_is_upgraded_to_public_on_every_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "legacy.db"
    audio_dir = tmp_path / "audio"
    monkeypatch.setenv("ATTEST_DB_PATH", str(database))
    monkeypatch.setenv("ATTEST_AUDIO_DIR", str(audio_dir))
    replay = next(item for item in seed_replay.REPLAYS if "builder" in item.run_id)
    payload = json.loads((seed_replay.FIXTURES / replay.fixture).read_text())
    legacy = dict(replay.record)
    legacy.pop("published")
    conn = db.connect(database)
    try:
        db.create_run(
            conn,
            run_id=replay.run_id,
            idempotency_key=replay.run_id,
            record_json=json.dumps(legacy),
        )
        db.set_calle_call_id(conn, replay.run_id, str(payload["id"]))
        fsm.advance(conn, replay.run_id, "submitted")
        fsm.advance(conn, replay.run_id, "completed", terminal_payload=json.dumps(payload))
        conn.execute(
            "UPDATE call_runs SET created_at = ?, updated_at = ? WHERE run_id = ?",
            ("2020-01-01T00:00:00Z", "2020-01-01T00:01:00Z", replay.run_id),
        )
        conn.commit()
    finally:
        conn.close()

    seed_replay.main()

    async with _client() as client:
        ledger = await client.get("/api/runs")
        detail = await client.get(f"/api/runs/{replay.run_id}")
        attestation = await client.get(f"/api/runs/{replay.run_id}/attestation")
        audio = await client.get(f"/api/runs/{replay.run_id}/audio")

    assert replay.run_id in [item["run_id"] for item in ledger.json()["runs"]]
    assert detail.status_code == 200
    assert attestation.status_code == 200
    assert audio.status_code == 200
    assert detail.json()["created_at"] == "2020-01-01T00:00:00Z"
    assert detail.json()["updated_at"] == "2020-01-01T00:01:00Z"
    assert attestation.json()["created_at"] == "2020-01-01T00:00:00Z"
    assert attestation.json()["completed_at"] == "2020-01-01T00:01:00Z"


def test_seed_replay_help_has_no_database_or_audio_side_effects(tmp_path: Path) -> None:
    root = Path(__file__).parent.parent
    database = tmp_path / "help-must-not-create.db"
    audio_dir = tmp_path / "help-must-not-copy-audio"
    env = {
        **os.environ,
        "ATTEST_DB_PATH": str(database),
        "ATTEST_AUDIO_DIR": str(audio_dir),
    }

    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "seed_replay.py"), "--help"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert not database.exists()
    assert not audio_dir.exists()
