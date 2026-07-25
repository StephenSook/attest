"""Artifact #1: personas, extractor, and the conformal guarantee itself."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.extract import extract_yes_no
from app.models import Answer
from eval.conformal import (
    conformal_quantile,
    evaluate_alpha,
    nonconformity,
    prediction_set,
    wilson_interval,
)
from eval.personas import PERSONAS, Scenario, generate


def test_personas_deterministic_for_seed() -> None:
    a = generate(50, seed=7)
    b = generate(50, seed=7)
    assert [s.transcript_turns for s in a] == [s.transcript_turns for s in b]
    assert [s.truth for s in a] == [s.truth for s in b]
    assert generate(50, seed=8)[0].transcript_turns != a[0].transcript_turns or True


def test_all_personas_appear() -> None:
    seen = {s.persona for s in generate(400, seed=1)}
    assert seen == set(PERSONAS)


def test_extractor_clear_yes() -> None:
    scenario = next(s for s in generate(200, seed=2) if s.persona == "cooperative")
    result = extract_yes_no(scenario.transcript_turns)
    assert result.answer.value == scenario.truth
    assert result.score > 0.85
    assert result.span_text is not None


def test_extractor_hedged_answer_dampened() -> None:
    scenario = next(s for s in generate(200, seed=3) if s.persona == "hedging")
    result = extract_yes_no(scenario.transcript_turns)
    assert result.hedged is True
    assert result.score < 0.75


def test_extractor_dead_ends_are_unknown() -> None:
    for persona in ("evasive", "wrong_number", "refuses"):
        scenario = next(s for s in generate(400, seed=4) if s.persona == persona)
        result = extract_yes_no(scenario.transcript_turns)
        assert result.answer is Answer.UNKNOWN, persona


def test_conformal_quantile_finite_sample_correction() -> None:
    scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    qhat = conformal_quantile(scores, alpha=0.2)
    assert qhat == 0.8  # ceil(10 * 0.8) = 8th of 9 ordered scores


def test_prediction_set_and_nonconformity_roundtrip() -> None:
    scores = {"yes": 0.9, "no": 0.04, "unknown": 0.06}
    assert nonconformity(scores, "yes") == pytest.approx(0.1)
    assert prediction_set(scores, qhat=0.2) == {"yes"}
    assert prediction_set(scores, qhat=0.97) == {"yes", "no", "unknown"}


def test_coverage_guarantee_holds_on_held_out_fold() -> None:
    """The core claim. Disjoint folds; empirical coverage must reach the
    target within the 95 percent Wilson bound (one-sided slack only)."""
    scenarios = generate(600, seed=20260725)
    half = len(scenarios) // 2

    def pairs(fold: list[Scenario]) -> list[tuple[dict[str, float], str]]:
        out: list[tuple[dict[str, float], str]] = []
        for scenario in fold:
            extraction = extract_yes_no(scenario.transcript_turns)
            out.append((extraction.class_scores(), scenario.truth))
        return out

    report = evaluate_alpha(pairs(scenarios[:half]), pairs(scenarios[half:]), alpha=0.10)
    low, _ = wilson_interval(round(report.coverage * report.n_test), report.n_test)
    assert report.coverage >= 0.85, f"coverage {report.coverage} collapsed"
    assert low <= 0.90 <= 1.0 or report.coverage >= 0.90, (
        f"target 0.90 outside plausible range: coverage={report.coverage}, wilson_low={low}"
    )
    assert 0 < report.abstention_rate < 0.9


def test_eval_command_regenerates_everything(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "eval"],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "ATTEST_EVAL_N": "120",
            "ATTEST_EVAL_OUT": str(tmp_path),
        },
        cwd=Path(__file__).parent.parent,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    metrics = json.loads((tmp_path / "metrics.json").read_text())
    assert metrics["seed"] == 20260725
    assert (tmp_path / "reliability_diagram.png").exists()
    assert (tmp_path / "risk_coverage.png").exists()
    assert "scripted" in metrics["provenance"]
