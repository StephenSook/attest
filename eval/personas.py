"""Six scripted adversarial respondent personas, seeded and deterministic.

These generate transcript_turns in the exact shape the real CALL-E payload
uses. They are the calibration and evaluation dataset: SCRIPTED SCENARIO DATA,
labeled at generation time, never presented as real calls anywhere.
"""

import random
from dataclasses import dataclass

PERSONAS = ("cooperative", "hedging", "contradictory", "evasive", "wrong_number", "refuses")

_WEIGHTS = {
    "cooperative": 0.40,
    "hedging": 0.20,
    "contradictory": 0.10,
    "evasive": 0.12,
    "wrong_number": 0.08,
    "refuses": 0.10,
}

# A hedged respondent is guessing; this often enough they guess wrong.
_HEDGE_WRONG_RATE = 0.35
# A contradictory respondent's FINAL statement is usually, not always, the truth.
_FINAL_STATEMENT_TRUTH_RATE = 0.70

_YES_CLEAR = ["Yes, we are.", "Yep.", "Yeah, absolutely.", "Yes, definitely taking new patients."]
_NO_CLEAR = [
    "No, we're not taking new patients right now.",
    "Unfortunately no, we're full.",
    "Nope, there's a waitlist.",
]
_YES_HEDGED = ["I think so, yes.", "Probably, yeah.", "I believe we are, yes.", "Pretty sure, yes."]
_NO_HEDGED = ["I think we stopped, no.", "Probably not, honestly.", "I believe we're full, no."]
_EVASIVE = [
    "You'd have to call back and speak to the office manager about that.",
    "I really can't answer that, you'd need to speak to billing.",
    "I don't know, the person who handles that is out today.",
]
_WRONG_NUMBER = [
    "I think you have the wrong number, this is a residence.",
    "Wrong number, there's no doctor's office here. Who is this?",
]
_REFUSES = [
    "I'm not comfortable answering questions from a robot, sorry.",
    "I'm not comfortable with this, please take us off your list.",
]

_BOT_OPENING = [
    {"offset_seconds": 0, "speaker": "bot", "text": "Hi,"},
    {
        "offset_seconds": 0,
        "speaker": "bot",
        "text": (
            "this is an automated assistant calling on behalf of a patient advocate "
            "to verify a directory listing."
        ),
    },
    {"offset_seconds": 6, "speaker": "bot", "text": "This call may be recorded."},
    {"offset_seconds": 13, "speaker": "user", "text": "Hello?"},
    {
        "offset_seconds": 14,
        "speaker": "bot",
        "text": "Is the practice currently accepting new patients?",
    },
]


@dataclass(frozen=True)
class Scenario:
    persona: str
    truth: str  # yes | no | unknown
    transcript_turns: list[dict[str, object]]


def _reply(rng: random.Random, persona: str, truth: str) -> str:
    if persona == "cooperative":
        return rng.choice(_YES_CLEAR if truth == "yes" else _NO_CLEAR)
    if persona == "hedging":
        stated = truth
        if rng.random() < _HEDGE_WRONG_RATE:
            stated = "no" if truth == "yes" else "yes"
        return rng.choice(_YES_HEDGED if stated == "yes" else _NO_HEDGED)
    if persona == "contradictory":
        first, second = ("Yes, we are.", "Actually wait, no, we stopped taking new patients.")
        if truth == "yes":
            first, second = ("No, I don't think so.", "Actually yes, we do have openings, yes.")
        return f"{first} ... {second}"
    if persona == "evasive":
        return rng.choice(_EVASIVE)
    if persona == "wrong_number":
        return rng.choice(_WRONG_NUMBER)
    return rng.choice(_REFUSES)


def generate(n: int, *, seed: int) -> list[Scenario]:
    rng = random.Random(seed)
    names = list(_WEIGHTS)
    weights = [_WEIGHTS[name] for name in names]
    scenarios: list[Scenario] = []
    for _ in range(n):
        persona = rng.choices(names, weights=weights, k=1)[0]
        if persona in {"evasive", "wrong_number", "refuses"}:
            truth = "unknown"
        elif persona == "contradictory":
            # The FINAL statement polarity defines what was stated; truth
            # matches it at the configured rate.
            truth = "no" if rng.random() < 0.5 else "yes"
        else:
            truth = rng.choice(["yes", "no"])
        reply = _reply(rng, persona, truth)
        if persona == "contradictory" and rng.random() > _FINAL_STATEMENT_TRUTH_RATE:
            truth = "no" if truth == "yes" else "yes"
        turns = [*_BOT_OPENING, {"offset_seconds": 19, "speaker": "user", "text": reply}]
        scenarios.append(Scenario(persona=persona, truth=truth, transcript_turns=turns))
    return scenarios
