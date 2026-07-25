"""Artifact #2: hedge lexicon, Fellegi-Sunter reconciliation, ablations."""

import math

from app.extract import extract_yes_no
from app.hedge import analyze
from app.models import Answer
from app.reconcile import reconcile
from eval.ablation import run_ablations
from eval.personas import generate


def test_hedge_analyze_finds_cues_with_offsets() -> None:
    result = analyze("I think we are, but I'm not sure honestly.")
    assert result.hedged is True
    assert result.strength == 1.0  # "not sure" outranks "i think"
    phrases = [cue.phrase.lower() for cue in result.cues]
    assert "i think" in phrases and "not sure" in phrases
    first = result.cues[0]
    assert (
        "I think we are, but I'm not sure honestly."[first.char_start : first.char_end].lower()
        == first.phrase.lower()
    )


def test_hedge_clean_text_is_clean() -> None:
    result = analyze("Yes, we are accepting new patients.")
    assert result.hedged is False
    assert result.dampen(0.9) == 0.9


def test_hedge_dampen_scales_with_strength() -> None:
    strong = analyze("Maybe, not sure.")
    mild = analyze("Pretty sure, yes.")
    assert strong.dampen(0.9) < mild.dampen(0.9) < 0.9


def test_reconcile_agreement_math() -> None:
    result = reconcile(
        call_answers={
            "office_name_confirmed": Answer.YES,
            "accepting_new_patients": Answer.YES,
            "accepts_plan": Answer.UNKNOWN,
        },
        directory_claims={
            "office_name_confirmed": Answer.YES,
            "accepting_new_patients": Answer.YES,
            "accepts_plan": Answer.YES,
        },
    )
    name = next(c for c in result.contributions if c.field == "office_name_confirmed")
    assert name.weight_bits == math.log2(0.95 / 0.30)
    plan = next(c for c in result.contributions if c.field == "accepts_plan")
    assert plan.agreed is None and plan.weight_bits == 0.0
    assert result.verdict == "verified"
    assert result.posterior_probability > 0.85


def test_reconcile_disagreement_contradicts() -> None:
    result = reconcile(
        call_answers={
            "office_name_confirmed": Answer.YES,
            "accepting_new_patients": Answer.NO,
            "accepts_plan": Answer.NO,
        },
        directory_claims={
            "office_name_confirmed": Answer.YES,
            "accepting_new_patients": Answer.YES,
            "accepts_plan": Answer.YES,
        },
    )
    assert result.posterior_probability < 0.5
    accepting = next(c for c in result.contributions if c.field == "accepting_new_patients")
    assert accepting.agreed is False and accepting.weight_bits < 0


def test_reconcile_no_evidence_is_unverifiable() -> None:
    result = reconcile(
        call_answers={},
        directory_claims={
            "office_name_confirmed": Answer.YES,
            "accepting_new_patients": Answer.YES,
            "accepts_plan": Answer.YES,
        },
    )
    assert result.verdict == "unverifiable"
    assert result.posterior_probability == 0.5


def test_extractor_spans_carry_char_offsets() -> None:
    scenario = next(s for s in generate(100, seed=11) if s.persona == "cooperative")
    result = extract_yes_no(scenario.transcript_turns)
    assert result.span_char_start is not None and result.span_char_end is not None
    assert result.span_text is not None
    span = result.span_text[result.span_char_start : result.span_char_end]
    assert span.strip() != ""


def test_ablation_shows_each_component_earning_its_place() -> None:
    scenarios = generate(400, seed=99)
    half = len(scenarios) // 2
    rows = {row.config: row for row in run_ablations(scenarios[:half], scenarios[half:], alpha=0.1)}
    assert set(rows) == {"full", "no_hedge", "no_dead_end", "no_calibration"}
    # Removing the dead-end guard lets wrong-number calls "answer", so
    # accuracy among answered must drop relative to the full pipeline.
    assert rows["no_dead_end"].accuracy_when_answering < rows["full"].accuracy_when_answering
    # Conformal configs report coverage; the fixed threshold cannot.
    assert rows["full"].coverage is not None
    assert rows["no_calibration"].coverage is None
