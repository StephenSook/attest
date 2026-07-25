#!/usr/bin/env python3
"""Extract a span-grounded answer from a CALL-E terminal payload.

Standard library only. Reads the payload saved by poll_result.py, walks the
transcript turns, and emits one JSON object per claim with the verbatim
supporting span and character offsets, or an explicit abstention. Hedged
answers keep their polarity at a dampened trust score. Non-responsive turns
(wrong number, refusal, call-back deflections) never count as answers.
"""

import argparse
import json
import re
import sys

YES_CUES = (
    r"\byes\b",
    r"\byeah\b",
    r"\byep\b",
    r"\babsolutely\b",
    r"\bcorrect\b",
    r"\bdefinitely\b",
    r"\bwe are\b",
    r"\bwe do\b",
    r"\bof course\b",
)
NO_CUES = (
    r"\bno\b",
    r"\bnope\b",
    r"\bnot accepting\b",
    r"\bnot taking\b",
    r"\bwe aren'?t\b",
    r"\bwe'?re not\b",
    r"\bunfortunately\b",
    r"\bfull\b",
    r"\bwaitlist\b",
    r"\bstopped\b",
    r"\bwe don'?t\b",
)
HEDGES = (
    (r"\bnot sure\b", 1.0),
    (r"\bno idea\b", 1.0),
    (r"\bi guess\b", 1.0),
    (r"\bmaybe\b", 1.0),
    (r"\bmight\b", 1.0),
    (r"\bpossibly\b", 1.0),
    (r"\bi think\b", 0.8),
    (r"\bi believe\b", 0.8),
    (r"\bprobably\b", 0.8),
    (r"\bas far as i know\b", 0.8),
    (r"\bpretty sure\b", 0.4),
    (r"\bshould be\b", 0.4),
)
DEAD_ENDS = (
    r"\bwrong number\b",
    r"\bresidence\b",
    r"\bwho is this\b",
    r"\bcall back\b",
    r"\bspeak to\b",
    r"\bnot comfortable\b",
    r"\bcan'?t answer\b",
    r"\bdon'?t know\b",
)
CLAIM_PATTERNS = {
    "accepting_new_patients": r"accepting new patients",
    # Word-bounded on purpose: "accepting" must NOT trigger this claim, or a
    # new-patients answer gets mis-attributed to the insurance question.
    "accepts_plan": r"\baccepts?\b|\btakes?\b.*\b(?:plan|insurance)\b|\bin[- ]network\b",
}
DAMPEN = 0.55  # keep in sync with app.hedge.MAX_DAMPEN in the main repo
ABSTAIN_BELOW = 0.65


def turns_from_payload(payload: dict) -> list[dict]:
    for recipient in payload.get("recipients", []):
        for attempt in recipient.get("attempts", []):
            turns = attempt.get("transcript_turns")
            if turns:
                return list(turns)
    return []


def first_span(cues: tuple[str, ...], text: str) -> tuple[int, int] | None:
    lowered = text.lower()
    best = None
    for cue in cues:
        match = re.search(cue, lowered)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), match.end())
    return best


def extract(turns: list[dict], claim: str, question_pattern: str) -> dict:
    question_seen = False
    yes_hit = no_hit = None
    hedge_strength = 0.0
    dead_end = False
    for index, turn in enumerate(turns):
        text = str(turn.get("text", ""))
        if turn.get("speaker") == "bot":
            if re.search(question_pattern, text.lower()):
                question_seen = True
            continue
        if not question_seen:
            continue
        if any(re.search(cue, text.lower()) for cue in DEAD_ENDS):
            dead_end = True
            continue
        for pattern, strength in HEDGES:
            if re.search(pattern, text.lower()):
                hedge_strength = max(hedge_strength, strength)
        span = first_span(YES_CUES, text)
        if span and yes_hit is None:
            yes_hit = (index, text, span)
        span = first_span(NO_CUES, text)
        if span and no_hit is None:
            no_hit = (index, text, span)

    hedged = hedge_strength > 0
    if (yes_hit is None) == (no_hit is None):
        # Neither, or contradictory both: abstain honestly.
        return {
            "claim": claim,
            "answer": "unknown",
            "trust_score": 0.85 if dead_end else 0.25 if yes_hit else 0.6,
            "hedged": hedged,
            "span": None,
            "abstain": True,
        }
    index, text, (start, end) = yes_hit or no_hit  # type: ignore[misc]
    score = 0.9 * (1.0 - DAMPEN * hedge_strength)
    return {
        "claim": claim,
        "answer": "yes" if yes_hit else "no",
        "trust_score": round(score, 3),
        "hedged": hedged,
        "span": {"turn": index, "text": text, "char_start": start, "char_end": end},
        "abstain": score < ABSTAIN_BELOW,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True, help="JSON file from poll_result.py")
    args = parser.parse_args()
    with open(args.payload, encoding="utf-8") as handle:
        payload = json.load(handle)
    turns = turns_from_payload(payload)
    if not turns:
        sys.exit("ERROR: no transcript turns found in payload.")
    for claim, pattern in CLAIM_PATTERNS.items():
        print(json.dumps(extract(turns, claim, pattern)))


if __name__ == "__main__":
    main()
