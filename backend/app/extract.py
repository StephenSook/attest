"""Transcript-side extraction: turn a conversation into a scored answer.

This is product code, not eval scaffolding: the same extractor runs on real
CALL-E transcript_turns. Every answer carries the supporting span (turn index
plus verbatim text) or is UNKNOWN. Hedged answers keep their polarity but get
a dampened trust score; the conformal layer downstream decides whether that
score clears the abstention bar.
"""

import re
from dataclasses import dataclass

from app.hedge import MAX_DAMPEN
from app.hedge import analyze as analyze_hedges
from app.models import Answer
from app.textnorm import normalize

_YES_CUES = (
    r"\byes\b",
    # guard the same way for the other agreement cues
    r"\byeah\b",
    r"\byep\b",
    r"\babsolutely\b",
    r"\bcorrect\b",
    r"\bdefinitely\b",
    # "we are not taking" must never read as agreement: without the
    # lookahead this matched inside a refusal and won the tie-break.
    r"\bwe are\b(?!\s+not\b)",
    r"\bsure are\b",
    r"\bof course\b",
)
_NO_CUES = (
    # "no problem" / "no worries" / "not at all" are agreement, not refusal.
    # Without this guard "Sure, no problem, we are accepting new patients"
    # extracts a confident NO, which is the worst failure this system can
    # produce: a wrong answer delivered with a highlighted span.
    r"\bno\b(?!\s+(?:problem|worries|trouble|issue|doubt)\b)",
    r"\bnope\b",
    r"\bnot accepting\b",
    r"\bnot taking\b",
    r"\bnot at all\b(?=.*\baccept)",
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
    lowered = normalize(text)
    return any(re.search(cue, lowered) for cue in cues)


def _last_span(cues: tuple[str, ...], text: str) -> tuple[int, int] | None:
    """The LAST cue occurrence of this polarity in the turn.

    Last, not first, because the documented rule is to trust the final clear
    statement. Taking the first occurrence made a refusal that opens with
    "Unfortunately no, we are full" lose the tie-break to the "we are" that
    appears later, and be served as a confident yes.
    """
    lowered = normalize(text)
    best: tuple[int, int] | None = None
    for cue in cues:
        for match in re.finditer(cue, lowered):
            if best is None or match.start() > best[0]:
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
    other_question_patterns: tuple[str, ...] = (),
    dead_end_guard: bool = True,
) -> ExtractionResult:
    """Extract a yes/no/unknown answer to the question from user turns.

    The answer window OPENS when the agent asks this question and CLOSES when
    it asks a different tracked one. Without the close it ran to the end of the
    call, so on a multi-question call the reply to a later question was also
    counted as the answer to an earlier one: a respondent who deflected on new
    patients and later said "Yes, we take that plan" had the new-patients claim
    reported as a confident yes, span-grounded to a sentence about insurance.
    A wrong answer carrying a citation is worse than no answer, because the
    citation is what invites belief.

    Callers extracting several claims from one transcript must pass the other
    claims' patterns. The default is empty so single-claim callers, including
    the eval harness, keep their existing behaviour exactly.

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
            lowered_bot = normalize(text)
            if re.search(question_pattern, lowered_bot):
                # Re-asking this claim reopens rather than closes the window.
                question_seen = True
            elif question_seen and any(
                re.search(other, lowered_bot) for other in other_question_patterns
            ):
                # The agent moved on. Everything after this answers that
                # question, not this one.
                break
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
        yes_span = _last_span(_YES_CUES, text)
        if yes_span:
            yes_hits.append(_Hit(index, text, yes_span[0], yes_span[1]))
        no_span = _last_span(_NO_CUES, text)
        if no_span:
            no_hits.append(_Hit(index, text, no_span[0], no_span[1]))

    hedged = hedge_strength > 0
    if dead_end and not yes_hits and not no_hits:
        return ExtractionResult(
            Answer.UNKNOWN, 0.85, hedged, hedge_strength, None, None, None, None
        )
    if yes_hits and no_hits:
        # Contradiction: trust the LAST clear statement, at low score.
        # Tie-break by character offset so a same-turn contradiction
        # ('Yes... actually no') trusts the LAST statement, not the list
        # order of the candidates.
        final = max(yes_hits + no_hits, key=lambda hit: (hit.turn, hit.char_start))
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
        score *= 1.0 - MAX_DAMPEN * hedge_strength
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
