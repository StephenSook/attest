"""Transcript-side extraction: turn a conversation into a scored answer.

This is product code, not eval scaffolding: the same extractor runs on real
CALL-E transcript_turns. Every answer carries the supporting span (turn index
plus verbatim text) or is UNKNOWN. Hedged answers keep their polarity but get
a dampened trust score; the conformal layer downstream decides whether that
score clears the abstention bar.
"""

import re
from dataclasses import dataclass

from app.hedge import analyze as analyze_hedges
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

_CONTRADICTION_SCORE = 0.25


@dataclass(frozen=True)
class ExtractionResult:
    answer: Answer
    score: float
    hedged: bool
    hedge_strength: float
    span_turn: int | None
    span_text: str | None
    span_char_start: int | None
    span_char_end: int | None

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


def _first_span(cues: tuple[str, ...], text: str) -> tuple[int, int] | None:
    lowered = text.lower()
    best: tuple[int, int] | None = None
    for cue in cues:
        match = re.search(cue, lowered)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), match.end())
    return best


@dataclass(frozen=True)
class _Hit:
    turn: int
    text: str
    char_start: int
    char_end: int


def extract_yes_no(
    turns: list[dict[str, object]],
    *,
    question_pattern: str = r"accepting new patients",
    dead_end_guard: bool = True,
) -> ExtractionResult:
    """Extract a yes/no/unknown answer to the question from user turns.

    dead_end_guard exists only so the eval ablation can demonstrate what
    happens without it; production callers never disable it.
    """
    question_seen = False
    yes_hits: list[_Hit] = []
    no_hits: list[_Hit] = []
    hedge_strength = 0.0
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
        if dead_end_guard and _find(_DEAD_END_CUES, text):
            # A dead-end turn ("wrong number", "you'd have to call back") is
            # non-responsive: polarity words inside it ("there's NO doctor's
            # office here") are not answers to the question.
            dead_end = True
            continue
        hedge_analysis = analyze_hedges(text)
        if hedge_analysis.hedged:
            hedge_strength = max(hedge_strength, hedge_analysis.strength)
        yes_span = _first_span(_YES_CUES, text)
        if yes_span:
            yes_hits.append(_Hit(index, text, yes_span[0], yes_span[1]))
        no_span = _first_span(_NO_CUES, text)
        if no_span:
            no_hits.append(_Hit(index, text, no_span[0], no_span[1]))

    hedged = hedge_strength > 0
    if dead_end and not yes_hits and not no_hits:
        return ExtractionResult(
            Answer.UNKNOWN, 0.85, hedged, hedge_strength, None, None, None, None
        )
    if yes_hits and no_hits:
        # Contradiction: trust the LAST clear statement, at low score.
        final = max(yes_hits + no_hits, key=lambda hit: hit.turn)
        answer = Answer.YES if final in yes_hits else Answer.NO
        return ExtractionResult(
            answer,
            _CONTRADICTION_SCORE,
            hedged,
            hedge_strength,
            final.turn,
            final.text,
            final.char_start,
            final.char_end,
        )
    if yes_hits or no_hits:
        hits = yes_hits or no_hits
        answer = Answer.YES if yes_hits else Answer.NO
        score = min(0.9 + 0.02 * (len(hits) - 1), 0.98)
        score *= 1.0 - 0.55 * hedge_strength
        first = hits[0]
        return ExtractionResult(
            answer,
            score,
            hedged,
            hedge_strength,
            first.turn,
            first.text,
            first.char_start,
            first.char_end,
        )
    return ExtractionResult(Answer.UNKNOWN, 0.6, hedged, hedge_strength, None, None, None, None)
