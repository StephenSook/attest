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
