"""Hedge detection: a graded epistemic cue lexicon.

Separates "yes" from "I think so." High precision over recall: every cue here
is a phrase whose presence reliably signals reduced commitment. Strength is
graded so downstream scoring can dampen proportionally, and every detection
carries its verbatim span with exact character offsets.
"""

import re
from dataclasses import dataclass

from app.textnorm import normalize

# strength: 1.0 = strong hedge (speaker flags real uncertainty),
#           0.8 = belief-verb (belief, not knowledge), 0.4 = mild softener.
_LEXICON: tuple[tuple[str, float], ...] = (
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
    (r"\bif i remember\b", 0.8),
    (r"\bpretty sure\b", 0.4),
    (r"\bshould be\b", 0.4),
    (r"\bi'?d say\b", 0.4),
)

# How much a hedge of full strength dampens a trust score.
MAX_DAMPEN = 0.55


@dataclass(frozen=True)
class HedgeCue:
    phrase: str
    strength: float
    char_start: int
    char_end: int


@dataclass(frozen=True)
class HedgeAnalysis:
    hedged: bool
    strength: float  # max cue strength found, 0.0 when clean
    cues: tuple[HedgeCue, ...]

    def dampen(self, score: float) -> float:
        """Scale a trust score by the strongest hedge found."""
        if not self.hedged:
            return score
        factor = 1.0 - MAX_DAMPEN * self.strength
        return score * max(factor, 1.0 - MAX_DAMPEN)


def analyze(text: str) -> HedgeAnalysis:
    lowered = normalize(text)
    cues: list[HedgeCue] = []
    for pattern, strength in _LEXICON:
        for match in re.finditer(pattern, lowered):
            cues.append(
                HedgeCue(
                    phrase=text[match.start() : match.end()],
                    strength=strength,
                    char_start=match.start(),
                    char_end=match.end(),
                )
            )
    if not cues:
        return HedgeAnalysis(hedged=False, strength=0.0, cues=())
    return HedgeAnalysis(
        hedged=True,
        strength=max(cue.strength for cue in cues),
        cues=tuple(sorted(cues, key=lambda cue: cue.char_start)),
    )
