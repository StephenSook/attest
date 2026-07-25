"""Transcript-side extraction: turn a conversation into a scored answer.

This is product code, not eval scaffolding: the same extractor runs on real
CALL-E transcript_turns. Every answer carries the supporting span (turn index
plus verbatim text) or is UNKNOWN. Hedged answers keep their polarity but get
a dampened trust score; the conformal layer downstream decides whether that
score clears the abstention bar.
"""

import re
from dataclasses import dataclass

from app.models import Answer

_YES_CUES = (
    r"\byes\b",
    r"\byeah\b",
    r"\byep\b",
    r"\babsolutely\b",
    r"\bcorrect\b",
    r"\bdefinitely\b",
    r"\bwe are\b",
    r"\bsure are\b",
    r"\bof course\b",
)
_NO_CUES = (
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
)
_HEDGE_CUES = (
    r"\bi think\b",
    r"\bmaybe\b",
    r"\bprobably\b",
    r"\bi believe\b",
    r"\bnot sure\b",
    r"\bpossibly\b",
    r"\bi guess\b",
    r"\bmight\b",
    r"\bpretty sure\b",
    r"\bas far as i know\b",
)
_DEAD_END_CUES = (
    r"\bwrong number\b",
    r"\bresidence\b",
    r"\bwho is this\b",
    r"\bcall back\b",
    r"\bspeak to\b",
    r"\bnot comfortable\b",
    r"\bcan'?t answer\b",
    r"\bdon'?t know\b",
)

_HEDGE_DAMPEN = 0.55
_CONTRADICTION_SCORE = 0.25


@dataclass(frozen=True)
class ExtractionResult:
    answer: Answer
    score: float
    hedged: bool
    span_turn: int | None
    span_text: str | None

    def class_scores(self) -> dict[str, float]:
        """A normalized score per class, consumed by the conformal layer."""
        s = self.score
        if self.answer is Answer.UNKNOWN:
            return {"yes": (1 - s) / 2, "no": (1 - s) / 2, "unknown": s}
        other = 1 - s
        if self.answer is Answer.YES:
            return {"yes": s, "no": other * 0.4, "unknown": other * 0.6}
        return {"yes": other * 0.4, "no": s, "unknown": other * 0.6}


def _find(cues: tuple[str, ...], text: str) -> bool:
    lowered = text.lower()
    return any(re.search(cue, lowered) for cue in cues)


def extract_yes_no(
    turns: list[dict[str, object]],
    *,
    question_pattern: str = r"accepting new patients",
) -> ExtractionResult:
    """Extract a yes/no/unknown answer to the question from user turns."""
    question_seen = False
    yes_hits: list[tuple[int, str]] = []
    no_hits: list[tuple[int, str]] = []
    hedged = False
    dead_end = False

    for index, turn in enumerate(turns):
        speaker = str(turn.get("speaker", ""))
        text = str(turn.get("text", ""))
        if speaker == "bot":
            if re.search(question_pattern, text.lower()):
                question_seen = True
            continue
        if not question_seen:
            continue
        if _find(_DEAD_END_CUES, text):
            # A dead-end turn ("wrong number", "you'd have to call back") is
            # non-responsive: polarity words inside it ("there's NO doctor's
            # office here") are not answers to the question.
            dead_end = True
            continue
        if _find(_HEDGE_CUES, text):
            hedged = True
        if _find(_YES_CUES, text):
            yes_hits.append((index, text))
        if _find(_NO_CUES, text):
            no_hits.append((index, text))

    if dead_end and not yes_hits and not no_hits:
        return ExtractionResult(Answer.UNKNOWN, 0.85, hedged, None, None)
    if yes_hits and no_hits:
        # Contradiction: trust the LAST clear statement, at low score.
        final_index, final_text = max(yes_hits + no_hits, key=lambda hit: hit[0])
        answer = Answer.YES if (final_index, final_text) in yes_hits else Answer.NO
        return ExtractionResult(answer, _CONTRADICTION_SCORE, hedged, final_index, final_text)
    if yes_hits or no_hits:
        hits = yes_hits or no_hits
        answer = Answer.YES if yes_hits else Answer.NO
        score = min(0.9 + 0.02 * (len(hits) - 1), 0.98)
        if hedged:
            score *= _HEDGE_DAMPEN
        return ExtractionResult(answer, score, hedged, hits[0][0], hits[0][1])
    return ExtractionResult(Answer.UNKNOWN, 0.6, hedged, None, None)
