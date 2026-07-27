"""Regression pins for the full-repo audit findings.

Each test here corresponds to a finding from the parallel review sweep and
fails if the fix regresses. Named by what breaks, not by finding number.
"""

import json
from pathlib import Path

import httpx
import pytest

from app import db, fsm
from app.calle import client as calle_client
from app.extract import extract_yes_no
from app.main import app
from app.models import Answer
from app.runs import build_task

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json").read_text()
)


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


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
        conn, run_id="run_pol", idempotency_key="run_pol", record_json=json.dumps({"org": "X"})
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
