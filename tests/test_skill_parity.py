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

import contextlib
import importlib.util
import io
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest import mock

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


def test_the_gate_never_answers_when_the_calibrated_set_says_unknown() -> None:
    """A singleton {unknown} set must abstain even when extraction reported a
    polar answer. The original gate tested `len(pset) != 1 or answer ==
    "unknown"`, which never checks that the singleton AGREES with the answer,
    so a low-trust "yes" whose calibrated set was exactly {"unknown"} was
    served as a confident yes. Found by an upstream maintainer, not by us.

    The reference harness could not reach this because it derives the answer
    as the argmax, and the argmax is "unknown" throughout this region. This
    test therefore uses an EXTRACTED answer, the way the skill and the served
    path do, which is the only way the bug is observable.
    """
    from eval.conformal import abstains as product_abstains

    hits = 0
    for i in range(1, 1000):
        trust = i / 1000
        for j in range(1, 1000):
            qhat = j / 1000
            for answer in ("yes", "no"):
                scores = skill_gate.class_scores(answer, trust)
                if skill_gate.prediction_set(scores, qhat) != {"unknown"}:
                    continue
                hits += 1
                assert skill_gate.abstains(scores, answer, qhat) is True, (
                    f"skill gate answered {answer!r} at trust={trust} qhat={qhat} "
                    "while the calibrated set was exactly {'unknown'}"
                )
                assert product_abstains(scores, answer, qhat) is True, (
                    f"product gate answered {answer!r} at trust={trust} qhat={qhat} "
                    "while the calibrated set was exactly {'unknown'}"
                )
    assert hits > 0, "the {unknown}-singleton region was never reached, so this proves nothing"


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


def test_an_identical_reverification_reuses_one_idempotency_key_that_day() -> None:
    """The obvious recovery from a lost response must be the safe one.

    The key used to be a fresh uuid4 per invocation, so an operator whose create
    request timed out and who re-ran the same command dialed a real office a
    second time. Deriving the key from the request makes the identical re-run
    collide with the original instead.
    """
    place = _load_skill_module("place_verify_call")
    args = ("Example Family Medicine", "+15550101234", "yes", "Example PPO")
    first = place.default_idempotency_key(*args, "2026-07-29")
    again = place.default_idempotency_key(*args, "2026-07-29")
    assert first == again


def test_a_different_listing_or_question_never_shares_a_key() -> None:
    """Collisions here would suppress a real call, which is the opposite
    failure and a silent one: the operator would be handed another listing's
    answer. Each field that changes the verification must change the key."""
    place = _load_skill_module("place_verify_call")
    day = "2026-07-29"
    base = place.default_idempotency_key("Org A", "+15550101234", "yes", "PPO", day)
    variants = {
        "org": place.default_idempotency_key("Org B", "+15550101234", "yes", "PPO", day),
        "phone": place.default_idempotency_key("Org A", "+15550101299", "yes", "PPO", day),
        "accepting": place.default_idempotency_key("Org A", "+15550101234", "no", "PPO", day),
        "plan": place.default_idempotency_key("Org A", "+15550101234", "yes", "HMO", day),
        "day": place.default_idempotency_key("Org A", "+15550101234", "yes", "PPO", "2026-07-30"),
    }
    for field, key in variants.items():
        assert key != base, f"changing {field} must change the idempotency key"
    assert len(set(variants.values())) == len(variants), "variants collided with each other"


def test_reverifying_the_same_listing_later_is_not_served_a_stale_answer() -> None:
    """The day scope is the point, not an accident.

    A key derived from the parameters alone would be permanent, so a monthly
    re-audit would collide with the first call forever and the platform would
    return the original answer without dialing. For a tool that exists to
    refuse unestablished answers, silently serving a stale one is worse than
    placing a duplicate call.
    """
    place = _load_skill_module("place_verify_call")
    args = ("Example Family Medicine", "+15550101234", "yes", None)
    assert place.default_idempotency_key(*args, "2026-07-29") != place.default_idempotency_key(
        *args, "2026-08-29"
    )


def test_the_key_is_printed_before_anything_is_dialed() -> None:
    """A key first disclosed in the success response is useless in the exact
    case it exists for, a lost response. The dry run must therefore already
    show the key the live run would use."""
    place = _load_skill_module("place_verify_call")
    argv = [
        "place_verify_call.py",
        "--org",
        "Example Family Medicine",
        "--phone",
        "+15550101234",
        "--claim-accepting-new-patients",
        "yes",
    ]
    buffer = io.StringIO()
    with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buffer):
        place.main()
    out = buffer.getvalue()
    expected = place.default_idempotency_key(
        "Example Family Medicine", "+15550101234", "yes", None, place.utc_day()
    )
    assert "DRY RUN" in out
    assert expected in out, "the dry run must disclose the key the live run would use"


def test_an_explicit_key_overrides_the_derived_one() -> None:
    """The escape hatch for the UTC-midnight edge, where a retry would
    otherwise derive a different key than the call it is retrying."""
    place = _load_skill_module("place_verify_call")
    argv = [
        "place_verify_call.py",
        "--org",
        "Example Family Medicine",
        "--phone",
        "+15550101234",
        "--claim-accepting-new-patients",
        "yes",
        "--idempotency-key",
        "verify-supplied-by-the-operator",
    ]
    buffer = io.StringIO()
    with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buffer):
        place.main()
    assert "verify-supplied-by-the-operator" in buffer.getvalue()


_SCRIPTS = _SKILL_SCRIPT.parent
_REPO = _SKILL_SCRIPT.parent.parent.parent.parent
_BUILDER_FIXTURE = _REPO / "mock_calle" / "fixtures" / "replay_builder_call.json"
_SAMPLE_CALL = _SKILL_SCRIPT.parent.parent / "references" / "sample-call.json"


def _run_reconcile(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "reconcile_record.py"),
            "--payload",
            str(_SAMPLE_CALL),
            "--org",
            "Example Family Medicine",
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_reconciliation_uses_the_calibrated_answer_instead_of_discarding_it() -> None:
    """The whole script was inert.

    reconcile_record.py runs extract_answer.py itself and never passed --qhat,
    so extraction fail-closed on every claim, every field arrived "unknown",
    and the run printed a 50 percent posterior and UNVERIFIABLE no matter what
    was said on the call. On this fixture the recipient plainly says they are
    accepting new patients, with a transcript span behind it, and that was
    reported as "no evidence". Reported by an upstream maintainer.
    """
    result = _run_reconcile("--qhat", "0.75", "--claim-accepting-new-patients", "yes")
    assert result.returncode == 0, result.stderr
    assert "call=yes record=yes" in result.stdout, (
        "the established answer was dropped again:\n" + result.stdout
    )
    assert "+1.36 bits" in result.stdout
    assert "= 50% record-accurate" not in result.stdout, (
        "an untouched prior means the evidence never reached the arithmetic"
    )


def test_reconciliation_can_actually_contradict_a_record() -> None:
    """The other half of the claim. A tool that can only ever say
    UNVERIFIABLE is not reconciling anything."""
    result = _run_reconcile("--qhat", "0.75", "--claim-accepting-new-patients", "no")
    assert result.returncode == 0, result.stderr
    assert "verdict: CONTRADICTED" in result.stdout, result.stdout


def test_reconciliation_refuses_without_a_threshold_rather_than_faking_a_verdict() -> None:
    """Failing closed is right for extraction and wrong here.

    An uncalibrated reconciliation cannot distinguish "the call established
    nothing" from "nobody looked", and printing UNVERIFIABLE with a tidy 50
    percent posterior presents the second as the first. Refusing is the only
    honest option for a script whose sole output is a verdict.
    """
    result = _run_reconcile("--claim-accepting-new-patients", "yes")
    assert result.returncode != 0
    assert "--qhat" in result.stderr
    assert "UNVERIFIABLE" not in result.stdout


def test_the_documented_reconciliation_example_is_the_real_output() -> None:
    """Run the command the docs print and diff against the output the docs
    claim. Hand-typed example output is how a number drifts from the code that
    produces it, which already happened once in this skill's calibration
    example."""
    doc = (_SCRIPTS.parent / "references" / "examples.md").read_text()
    block = doc.split("## Example 3")[1]
    documented = block.split("```text")[1].split("```")[0].strip()
    result = _run_reconcile(
        "--qhat",
        "0.750",
        "--claim-accepting-new-patients",
        "yes",
        "--claim-plan-accepted",
        "yes",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == documented, (
        "examples.md no longer matches what the command prints.\n"
        f"documented:\n{documented}\n\nactual:\n{result.stdout.strip()}"
    )


_TWO_QUESTION_CALL = [
    {
        "speaker": "bot",
        "text": (
            "Hi, this is an automated assistant verifying directory information. "
            "Are you currently accepting new patients?"
        ),
    },
    {"speaker": "user", "text": "Hmm, I'd have to look into that one."},
    {"speaker": "bot", "text": "Understood. And does the practice accept the Example PPO plan?"},
    {"speaker": "user", "text": "Yes, we take that plan."},
]


def test_a_later_answer_is_not_credited_to_an_earlier_question() -> None:
    """The worst bug in this skill: a wrong answer carrying a citation.

    The answer window opened when the agent asked a claim's question and never
    closed, so on a two-question call the reply to the second question was also
    read as the answer to the first. Here the respondent never answers the
    new-patients question, and the old code reported it as a confident yes,
    trust 0.9, not abstaining, span-grounded to "Yes, we take that plan.", a
    sentence plainly about insurance. Span grounding is the integrity
    mechanism, so pointing it at the wrong sentence is worse than abstaining.
    """
    others = tuple(
        p for name, p in skill.CLAIM_PATTERNS.items() if name != "accepting_new_patients"
    )
    result = skill.extract(
        _TWO_QUESTION_CALL,
        "accepting_new_patients",
        skill.CLAIM_PATTERNS["accepting_new_patients"],
        others,
    )
    assert result["answer"] == "unknown", (
        "the insurance answer was credited to the new-patients claim again: " + repr(result)
    )
    assert result["span"] is None, "an unanswered claim must not carry a span"


def test_closing_one_window_does_not_break_the_question_that_was_answered() -> None:
    """The boundary must cut in one direction only. The second question was
    genuinely answered and must still be extracted, with its own span."""
    others = tuple(p for name, p in skill.CLAIM_PATTERNS.items() if name != "accepts_plan")
    result = skill.extract(
        _TWO_QUESTION_CALL, "accepts_plan", skill.CLAIM_PATTERNS["accepts_plan"], others
    )
    assert result["answer"] == "yes"
    assert result["span"]["text"] == "Yes, we take that plan."


def test_an_acknowledgement_between_question_and_answer_keeps_the_window_open() -> None:
    """Only another tracked question closes the window. A bot turn that asks
    nothing, an acknowledgement or a hold request, must not orphan an answer
    that has not been given yet."""
    turns = [
        {"speaker": "bot", "text": "Are you currently accepting new patients?"},
        {"speaker": "bot", "text": "Take your time, I can hold."},
        {"speaker": "user", "text": "Yes, we are."},
    ]
    others = tuple(
        p for name, p in skill.CLAIM_PATTERNS.items() if name != "accepting_new_patients"
    )
    result = skill.extract(
        turns, "accepting_new_patients", skill.CLAIM_PATTERNS["accepting_new_patients"], others
    )
    assert result["answer"] == "yes", repr(result)


_REASSIGNED_NUMBER = [
    {
        "speaker": "bot",
        "text": (
            "Hi, this is an automated assistant verifying directory information "
            "for Example Family Medicine. Are you currently accepting new patients?"
        ),
    },
    {"speaker": "user", "text": "You've reached Riverside Auto Body, not a doctor. "},
    {"speaker": "user", "text": "But yes, we are open and taking new customers."},
]


def test_a_reassigned_number_is_not_evidence_about_the_listing() -> None:
    """Phone numbers get reassigned, and the new holder can answer clearly.

    "Yes, we are open and taking new customers" is a true sentence from a body
    shop. Recording it against a medical listing would manufacture precisely the
    false confirmation this tool exists to prevent, so identity has to be
    settled before any answer counts.
    """
    assert skill.organization_denied(_REASSIGNED_NUMBER) is True
    assert skill.organization_denied(_TWO_QUESTION_CALL) is False


def test_identity_is_tracked_separately_from_a_dead_end() -> None:
    """A dead end makes one claim unanswerable. A denied identity invalidates
    the entire call as evidence about this listing, however cleanly the
    questions were answered, so it cannot just be another dead-end cue."""
    turns = [
        {"speaker": "bot", "text": "Are you currently accepting new patients?"},
        {"speaker": "user", "text": "This is a residence, you have the wrong number."},
    ]
    assert skill.organization_denied(turns) is True


def test_the_call_script_tells_the_agent_to_confirm_the_organization_first() -> None:
    """The detector only catches a denial the respondent volunteers. The agent
    has to actually establish identity before asking, so the instruction is
    pinned here in both copies of the conduct block."""
    from app.runs import CALL_CONDUCT

    place = _load_skill_module("place_verify_call")
    for text in (CALL_CONDUCT, place.CALL_CONDUCT):
        lowered = text.lower()
        assert "first establish that you have reached the organization" in lowered
        assert "not evidence about this listing" in lowered


def test_every_skill_script_runs_on_the_python_version_the_docs_promise() -> None:
    """The skill ships into repositories we do not control.

    `def f(x: str | None)` evaluates its annotation at definition time, so on
    Python 3.9 importing these scripts died with "unsupported operand type(s)
    for |: 'type' and 'NoneType'" before argparse ever ran. The documented
    quick start simply did not work on the interpreter many repositories still
    default to, and nothing declared a minimum version.

    `from __future__ import annotations` makes annotations lazy and is what
    holds the 3.9 floor, so its presence is asserted per file rather than
    trusted to survive the next edit.
    """
    scripts = sorted((_SKILL_SCRIPT.parent).glob("*.py"))
    assert scripts, "no skill scripts found"
    for path in scripts:
        assert "from __future__ import annotations" in path.read_text(), (
            f"{path.name} drops the future-annotations import, which breaks the "
            "documented Python 3.9 floor at import time"
        )


def test_the_documented_python_floor_is_stated() -> None:
    """A version requirement nobody wrote down is a version requirement nobody
    can rely on."""
    skill_md = (_SKILL_SCRIPT.parent.parent / "SKILL.md").read_text()
    assert "**3.9**" in skill_md and "**3.11**" in skill_md, (
        "SKILL.md must state BOTH floors: 3.9 for the stdlib scripts and 3.11 for calle-ai"
    )


def test_the_saved_payload_is_not_world_readable(tmp_path: Path) -> None:
    """The payload holds a real person's phone number and verbatim words.

    It was written at the default 0644, world-readable on any shared machine,
    by a tool whose whole job is dialing strangers. Both cases are checked
    because O_CREAT only honours its mode when it actually creates the file, so
    re-running over an existing 0644 path would otherwise keep it loose.
    """
    poll = _load_skill_module("poll_result")
    fresh = tmp_path / "fresh.json"
    poll.write_payload({"status": "completed"}, str(fresh))
    assert fresh.stat().st_mode & 0o777 == 0o600, oct(fresh.stat().st_mode & 0o777)

    stale = tmp_path / "stale.json"
    stale.write_text("{}")
    stale.chmod(0o644)
    poll.write_payload({"status": "completed"}, str(stale))
    assert stale.stat().st_mode & 0o777 == 0o600, (
        "re-running over an existing world-readable payload left it world-readable"
    )


def test_retention_and_the_payload_sensitivity_are_documented() -> None:
    """A 0600 file the operator leaves on disk forever is still a liability.
    The skill cannot set a retention policy it has no standing to choose, so it
    must at least say what the file is and when to delete it."""
    safety = (_SKILL_SCRIPT.parent.parent / "references" / "safety.md").read_text().lower()
    for required in ("0600", "retention", "delete"):
        assert required in safety, f"safety.md no longer documents {required!r}"


def test_the_documented_calibration_example_is_the_real_output() -> None:
    """The number that was wrong.

    examples.md documented a 43.3 percent abstention rate while the command
    printed 60.0 percent. Verified to be stale independently of any change in
    this branch: the old gate prints 60.0 percent too. For a project whose
    entire claim is that its published numbers regenerate from the code, a
    hand-typed figure drifting from the program is the most damaging possible
    kind of error, so the example is now diffed against the real output rather
    than trusted.
    """
    scripts = _SKILL_SCRIPT.parent
    doc = (scripts.parent / "references" / "examples.md").read_text()
    documented = doc.split("## Example 4")[1].split("```text")[1].split("```")[0].strip()
    result = subprocess.run(
        [
            sys.executable,
            str(scripts / "calibrate.py"),
            "--data",
            str(scripts.parent / "references" / "sample-scenarios.jsonl"),
            "--alpha",
            "0.1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == documented, (
        "examples.md no longer matches what calibrate.py prints.\n"
        f"documented:\n{documented}\n\nactual:\n{result.stdout.strip()}"
    )


def test_the_documented_verdict_thresholds_match_the_code() -> None:
    """The remaining hand-typed numbers in the docs are the verdict bars.
    They are prose, so nothing regenerates them; pin them to the constants."""
    recon = _load_skill_module("reconcile_record")
    doc = (_SKILL_SCRIPT.parent.parent / "references" / "examples.md").read_text()
    assert f"{recon.VERIFIED_AT:.0%}".replace("%", " percent") in doc
    assert f"{recon.CONTRADICTED_AT:.0%}".replace("%", " percent") in doc


def _extract(payload: Path, *extra: str) -> list[dict[str, object]]:
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS / "extract_answer.py"), "--payload", str(payload), *extra],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return [__import__("json").loads(line) for line in result.stdout.strip().splitlines()]


def _write(tmp_path: Path, turns: list[dict[str, str]]) -> Path:
    p = tmp_path / "payload.json"
    p.write_text(
        __import__("json").dumps({"recipients": [{"attempts": [{"transcript_turns": turns}]}]})
    )
    return p


def test_identity_fails_closed_rather_than_open(tmp_path: Path) -> None:
    """Absence of a denial is not confirmation.

    Detecting an explicit "wrong number" was only half the job. Wrong numbers,
    answering services, shared reception desks and reassigned lines all produce
    cooperative respondents who answer clearly and are not the listing.
    Accepting those answers is how a verification tool manufactures a false
    confirmation. Found by an upstream maintainer on the second review pass.
    """
    turns = [
        {
            "speaker": "bot",
            "text": "Verifying directory information for Northside Family Medicine.",
        },
        {"speaker": "user", "text": "Sure, go ahead."},
        {"speaker": "bot", "text": "Are you currently accepting new patients?"},
        {"speaker": "user", "text": "Yes, we are."},
    ]
    records = _extract(
        _write(tmp_path, turns), "--qhat", "0.75", "--org", "Northside Family Medicine"
    )
    for r in records:
        assert r["abstain"] is True, f"answered without confirmed identity: {r}"
        assert r["gate"] == "identity-unconfirmed"
        assert r["span"] is None
        assert r["organization_confirmed"] is False


def test_a_named_confirmation_unlocks_the_answer(tmp_path: Path) -> None:
    """The gate must not be impossible to pass, or the skill is useless. Saying
    the practice name is the ordinary way a real front desk answers."""
    turns = [
        {
            "speaker": "bot",
            "text": "Verifying directory information for Northside Family Medicine.",
        },
        {"speaker": "user", "text": "Northside, this is the front desk."},
        {"speaker": "bot", "text": "Are you currently accepting new patients?"},
        {"speaker": "user", "text": "Yes, we are."},
    ]
    records = _extract(
        _write(tmp_path, turns), "--qhat", "0.75", "--org", "Northside Family Medicine"
    )
    answered = [r for r in records if not r["abstain"]]
    assert answered, "a named confirmation must let a clearly answered claim through"
    assert answered[0]["organization_confirmed"] is True


def test_both_questions_in_one_turn_abstains_on_both(tmp_path: Path) -> None:
    """A single "Yes." cannot be split between two claims after the fact.

    The old code handed that one reply to BOTH claims, each non-abstaining and
    each citing the same span. At least one of those is wrong and both look
    identically confident, which is the exact failure mode this project exists
    to prevent.
    """
    turns = [
        {
            "speaker": "bot",
            "text": "Verifying directory information for Northside Family Medicine.",
        },
        {"speaker": "user", "text": "Yes, this is Northside."},
        {
            "speaker": "bot",
            "text": "Are you accepting new patients, and does the practice accept Example PPO?",
        },
        {"speaker": "user", "text": "Yes."},
    ]
    records = _extract(
        _write(tmp_path, turns), "--qhat", "0.75", "--org", "Northside Family Medicine"
    )
    assert len(records) == 2
    for r in records:
        assert r["abstain"] is True, f"combined question served an answer: {r}"
        assert r["gate"] == "combined-question"
        assert r["span"] is None


def test_a_call_with_no_transcript_emits_abstentions_not_an_error(tmp_path: Path) -> None:
    """Nobody answering is the most common real outcome, and it is exactly when
    the promised explicit abstention matters most. This used to exit 1 with an
    error, which broke every downstream caller on the ordinary case and emitted
    no record at all."""
    records = _extract(_write(tmp_path, []), "--qhat", "0.75", "--org", "Example Family Medicine")
    assert len(records) == 2, "every tracked claim needs an explicit abstention record"
    for r in records:
        assert r["answer"] == "unknown"
        assert r["abstain"] is True
        assert r["gate"] == "no-transcript"


def test_a_run_with_no_claim_is_refused_before_dialing() -> None:
    """The claimless task asked "whether the published listing information is
    current", which no claim pattern matches, so the call could never produce a
    recordable answer. Spending a real call and a real person's time on that is
    worse than a crash."""
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "place_verify_call.py"),
            "--org",
            "Example Family Medicine",
            "--phone",
            "+15550101234",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "nothing to verify" in result.stderr.lower()

    place = _load_skill_module("place_verify_call")
    with pytest.raises(ValueError):
        place.build_task("Example Family Medicine", None, None)


def test_the_call_script_asks_identity_first_and_one_question_at_a_time() -> None:
    """Both agent-side halves of the two findings above. Extraction fails
    closed without a confirmation and abstains on a combined turn, so a script
    that never asks, or asks both at once, guarantees an abstention."""
    place = _load_skill_module("place_verify_call")
    task = place.build_task("Example Family Medicine", "yes", "Example PPO")
    assert "confirm you have reached the right place" in task
    assert "ONE question at a time" in task
    assert task.index("confirm you have reached") < task.index("accepting new patients")


def test_the_required_care_boundaries_are_documented() -> None:
    """The upstream repository requires boundaries for medical, legal,
    financial and emergency content. This skill calls healthcare
    organizations, so they are load-bearing rather than boilerplate."""
    safety = (_SKILL_SCRIPT.parent.parent / "references" / "safety.md").read_text().lower()
    for required in ("medical", "legal", "financial", "emergency", "988", "diagnosis"):
        assert required in safety, f"safety.md does not cover {required!r}"


def test_a_negated_organization_name_denies_rather_than_confirms() -> None:
    """The inverted case, reported on the third review pass.

    "No, this is not Example Family Medicine" matched no IDENTITY_DENIALS cue,
    and the name tokens inside the sentence then made organization_confirmed()
    return True. An explicit denial read as a confirmation is worse than
    fail-open: the call would continue and later answers would be attributed to
    a party that had just said it is not the listing.
    """
    org = "Example Family Medicine"
    denial = [
        {"speaker": "bot", "text": "Is this Example Family Medicine?"},
        {"speaker": "user", "text": "No, this is not Example Family Medicine."},
    ]
    assert skill.organization_denied(denial, org) is True
    assert skill.organization_confirmed(denial, org) is False


def test_a_denial_survives_a_cooperative_answer_afterwards() -> None:
    """Denial is a property of the call, not of one turn. Whoever holds the
    number now may answer helpfully; that is not evidence about the listing."""
    org = "Example Family Medicine"
    turns = [
        {"speaker": "bot", "text": "Is this Example Family Medicine?"},
        {
            "speaker": "user",
            "text": "No, this isn't Example Family Medicine, this is Riverside Auto.",
        },
        {"speaker": "bot", "text": "Are you currently accepting new patients?"},
        {"speaker": "user", "text": "Yes, we take walk-ins."},
    ]
    assert skill.organization_denied(turns, org) is True
    assert skill.organization_confirmed(turns, org) is False


def test_a_negation_elsewhere_in_a_confirming_turn_still_confirms() -> None:
    """The negation window is scoped to just before the name on purpose.
    "Yes, this is Example Family Medicine, not the Buckhead office" contains a
    negation and is a confirmation, so a whole-turn negation check would break
    the ordinary case while fixing the inverted one."""
    org = "Example Family Medicine"
    turns = [
        {"speaker": "bot", "text": "Is this Example Family Medicine?"},
        {
            "speaker": "user",
            "text": "Yes, this is Example Family Medicine, not the Buckhead office.",
        },
    ]
    assert skill.organization_denied(turns, org) is False
    assert skill.organization_confirmed(turns, org) is True


def test_every_operator_facing_command_carries_the_required_flags() -> None:
    """Printed and documented commands are operator-facing and must be runnable
    exactly as shown. calibrate.py and poll_result.py both printed a next-step
    command without --org, so following them produced identity-unconfirmed
    abstentions rather than the result the surrounding output implied. Same
    class of drift as the documented-number bug from the first review."""
    import re as _re

    scripts_dir = _SKILL_SCRIPT.parent
    for name in ("calibrate.py", "poll_result.py"):
        src = (scripts_dir / name).read_text()
        joined = " ".join(src.splitlines())
        if "extract_answer.py --payload" in joined or "extract_answer.py " in joined:
            assert "--org" in joined, f"{name} prints an extract command without --org"

    for doc in ("SKILL.md", "references/examples.md"):
        src = (scripts_dir.parent / doc).read_text()
        joined = _re.sub(r"\\\n\s*", " ", src)
        for line in joined.splitlines():
            if "extract_answer.py" in line and "--payload" in line:
                assert "--org" in line, (
                    f"{doc} documents an extract command without --org: {line[:80]}"
                )
            if "reconcile_record.py" in line and "--payload" in line:
                assert "--org" in line, (
                    f"{doc} documents a reconcile command without --org: {line[:80]}"
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
