"""The shipped skill must answer exactly what the product answers.

skills/verify-by-phone is the artifact that goes upstream: it is installed on
machines that never see this repository, so it carries its own standard-library
copy of the extractor. A copy drifts. SKILL.md used to ask a human to re-sync it
by hand, which is the same sync-by-comment pattern that let the abstention gate
diverge from the harness, and it had already failed: the backend learned to
trust the LAST cue in a turn and to read "no problem" as agreement, while the
skill still trusted the first cue and read any bare "no" as refusal.

This test is the enforcement. Both extractors run on the same transcripts and
must produce the same answer. A behavior change to backend/app/extract.py that
is not mirrored into the skill fails here, in CI, on the commit that causes it.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.extract import extract_yes_no
from app.models import Answer

_SKILL_SCRIPT = (
    Path(__file__).parent.parent / "skills" / "verify-by-phone" / "scripts" / "extract_answer.py"
)


def _load_skill_module(name: str) -> ModuleType:
    """Import a skill script by path: they are deliberately not a package.

    The scripts import their sibling gate.py the way Python resolves imports
    for a directly executed script, so the scripts directory has to be on the
    path here the way the interpreter would put it there.
    """
    path = _SKILL_SCRIPT.parent / f"{name}.py"
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(f"skill_{name}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(path.parent))


skill = _load_skill_module("extract_answer")
skill_gate = _load_skill_module("gate")

QUESTION = "Is the practice currently accepting new patients?"
CLAIM_PATTERN = r"accepting new patients"

# Each case is one respondent reply to the accepting-new-patients question.
# The names describe the linguistic trap, not the expected label, so a wrong
# expectation cannot hide behind an agreeable name.
CASES = [
    ("plain yes", "Yes, we are."),
    ("plain no", "No, we are not."),
    # The bug this test was written for: "we are" sits inside the refusal.
    ("refusal containing an agreement cue", "No, we are not taking new patients right now."),
    # The mirror image: "no problem" is agreement, not refusal.
    ("agreement containing a refusal cue", "Sure, no problem, we are accepting new patients."),
    ("refusal opening with a hedge word", "Unfortunately no, we are full at the moment."),
    ("same-turn correction", "Yes we are, actually no, we stopped last month."),
    ("hedged yes", "I think so, yes."),
    ("hedged no", "I'm not sure, but probably not, we're pretty full."),
    ("waitlist refusal", "We have a waitlist right now."),
    ("dead end", "You have the wrong number, this is a residence."),
    ("non-responsive", "It's been a busy morning here."),
]


def _turns(reply: str) -> list[dict[str, object]]:
    return [
        {"speaker": "bot", "text": QUESTION},
        {"speaker": "user", "text": reply},
    ]


@pytest.mark.parametrize("label,reply", CASES, ids=[case[0] for case in CASES])
def test_skill_extractor_agrees_with_the_product(label: str, reply: str) -> None:
    turns = _turns(reply)
    product = extract_yes_no(turns, question_pattern=CLAIM_PATTERN)
    shipped = skill.extract(turns, "accepting_new_patients", CLAIM_PATTERN)

    product_answer = {Answer.YES: "yes", Answer.NO: "no", Answer.UNKNOWN: "unknown"}[product.answer]
    assert shipped["answer"] == product_answer, (
        f"{label}: the shipped skill says {shipped['answer']!r} where the product "
        f"says {product_answer!r}. Mirror the backend change into "
        f"skills/verify-by-phone/scripts/extract_answer.py."
    )


@pytest.mark.parametrize("label,reply", CASES, ids=[case[0] for case in CASES])
def test_skill_cites_the_same_span(label: str, reply: str) -> None:
    """An answer is only as good as the span under it: a matching label with a
    span pointing at different words would still mislead a reviewer."""
    turns = _turns(reply)
    product = extract_yes_no(turns, question_pattern=CLAIM_PATTERN)
    shipped = skill.extract(turns, "accepting_new_patients", CLAIM_PATTERN)

    if product.span_char_start is None:
        assert shipped["span"] is None, f"{label}: skill cites a span where the product abstains"
        return
    span = shipped["span"]
    assert span is not None, f"{label}: skill cites no span where the product cites one"
    assert (span["char_start"], span["char_end"]) == (
        product.span_char_start,
        product.span_char_end,
    ), (
        f"{label}: skill highlights {reply[span['char_start'] : span['char_end']]!r}, "
        f"product highlights {reply[product.span_char_start : product.span_char_end]!r}"
    )


@pytest.mark.parametrize("answer", ["yes", "no", "unknown"])
@pytest.mark.parametrize("trust", [0.25, 0.6, 0.85, 0.9, 0.98])
@pytest.mark.parametrize("qhat", [0.2, 0.5, 0.75, 0.9])
def test_skill_gate_matches_the_product_gate(answer: str, trust: float, qhat: float) -> None:
    """The gate drifted once already, between the harness and the served path.
    The skill carries a third copy, so it gets pinned to the same rule here."""
    from eval.conformal import abstains as product_abstains

    skill_scores = skill_gate.class_scores(answer, trust)
    assert skill_gate.abstains(skill_scores, answer, qhat) == product_abstains(
        skill_scores, answer, qhat
    )


def test_uncalibrated_extraction_fails_closed() -> None:
    """Without a calibrated threshold there is no guarantee to answer behind,
    so the skill must abstain and say why rather than invent a threshold."""
    result = skill.apply_gate(
        {"claim": "c", "answer": "yes", "trust_score": 0.9, "hedged": False, "span": None},
        None,
    )
    assert result["abstain"] is True
    assert result["gate"] == "uncalibrated"


def test_calibrated_extraction_answers_a_clean_yes() -> None:
    """The counterpart: a confident answer under a calibrated gate is served.
    Without this, 'fails closed' could be satisfied by never answering."""
    result = skill.apply_gate(
        {"claim": "c", "answer": "yes", "trust_score": 0.9, "hedged": False, "span": None},
        0.5,
    )
    assert result["abstain"] is False
    assert result["gate"] == "conformal(qhat=0.500)"


def test_call_conduct_is_identical() -> None:
    """The third copy nobody was checking.

    The task text is not just prose: it is the only thing standing between the
    agent and inventing a date of birth when a receptionist asks for one. The
    two builders had already drifted, the skill having no voicemail rule at all,
    so the conduct block is pinned here the same way the cue lexicons are.
    """
    from app.runs import CALL_CONDUCT as product_conduct

    place = _load_skill_module("place_verify_call")
    assert product_conduct == place.CALL_CONDUCT, (
        "The shipped skill's call conduct has drifted from the product's. "
        "Mirror backend/app/runs.py CALL_CONDUCT into "
        "skills/verify-by-phone/scripts/place_verify_call.py."
    )


def test_the_agent_is_told_to_refuse_identity_prompts() -> None:
    """Behavioral intent, stated once so a future edit cannot quietly drop it.

    A clinic asks the caller for a name, a date of birth, and often an insurance
    card number. An agent that invents one to keep the conversation moving would
    be actively harmful and would contradict the product's entire claim, so the
    instruction not to is asserted rather than assumed.
    """
    from app.runs import CALL_CONDUCT

    lowered = CALL_CONDUCT.lower()
    for required in ("date of birth", "card number", "never invent"):
        assert required in lowered, f"the call conduct no longer covers {required!r}"


def test_cue_lexicons_are_identical() -> None:
    """Behavioral parity above, textual parity here: a cue added to the backend
    that changes no case in this file still has to be carried across."""
    from app import extract as backend

    assert tuple(skill.YES_CUES) == backend._YES_CUES
    assert tuple(skill.NO_CUES) == backend._NO_CUES
    assert tuple(skill.DEAD_ENDS) == backend._DEAD_END_CUES
