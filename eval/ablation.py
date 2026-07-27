"""Ablation table: what each component of the pipeline actually buys.

Four configurations over the same disjoint folds:
  full            the shipped pipeline
  no_hedge        hedge dampening removed (scores un-dampened)
  no_dead_end     dead-end guard off: wrong-number calls can "answer"
  no_calibration  conformal sets replaced by a fixed 0.5 score threshold
"""

import dataclasses
from dataclasses import dataclass

from app.extract import ExtractionResult, extract_yes_no
from app.hedge import MAX_DAMPEN
from eval.conformal import evaluate_alpha
from eval.personas import Scenario


@dataclass(frozen=True)
class AblationRow:
    config: str
    coverage: float | None  # conformal configs only
    abstention_rate: float
    accuracy_when_answering: float


def _undampened(extraction: ExtractionResult) -> ExtractionResult:
    if not extraction.hedged:
        return extraction
    factor = 1.0 - MAX_DAMPEN * extraction.hedge_strength
    return dataclasses.replace(extraction, score=min(extraction.score / factor, 0.98))


def _conformal_row(
    name: str,
    cal: list[tuple[dict[str, float], str]],
    test: list[tuple[dict[str, float], str]],
    alpha: float,
) -> AblationRow:
    report = evaluate_alpha(cal, test, alpha)
    return AblationRow(
        config=name,
        coverage=report.coverage,
        abstention_rate=report.abstention_rate,
        accuracy_when_answering=report.singleton_accuracy,
    )


def run_ablations(
    calibration: list[Scenario], test: list[Scenario], *, alpha: float
) -> list[AblationRow]:
    def extractions(
        fold: list[Scenario], *, guard: bool, dampen: bool
    ) -> list[tuple[ExtractionResult, str]]:
        out: list[tuple[ExtractionResult, str]] = []
        for scenario in fold:
            extraction = extract_yes_no(scenario.transcript_turns, dead_end_guard=guard)
            if not dampen:
                extraction = _undampened(extraction)
            out.append((extraction, scenario.truth))
        return out

    def pairs(items: list[tuple[ExtractionResult, str]]) -> list[tuple[dict[str, float], str]]:
        return [(extraction.class_scores(), truth) for extraction, truth in items]

    rows: list[AblationRow] = []
    for name, guard, dampen in (
        ("full", True, True),
        ("no_hedge", True, False),
        ("no_dead_end", False, True),
    ):
        cal = pairs(extractions(calibration, guard=guard, dampen=dampen))
        tst = pairs(extractions(test, guard=guard, dampen=dampen))
        rows.append(_conformal_row(name, cal, tst, alpha))

    # no_calibration: fixed threshold on the trust score, no conformal sets.
    test_items = extractions(test, guard=True, dampen=True)
    answered = [(extraction, truth) for extraction, truth in test_items if extraction.score >= 0.5]
    correct = sum(1 for extraction, truth in answered if extraction.answer.value == truth)
    rows.append(
        AblationRow(
            config="no_calibration",
            coverage=None,
            abstention_rate=1 - len(answered) / len(test_items),
            accuracy_when_answering=(correct / len(answered)) if answered else float("nan"),
        )
    )
    return rows


def as_markdown(rows: list[AblationRow]) -> str:
    lines = [
        "| Config | Coverage (target in set) | Abstention | Accuracy when answering |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        coverage = f"{row.coverage:.1%}" if row.coverage is not None else "n/a"
        lines.append(
            f"| {row.config} | {coverage} | {row.abstention_rate:.1%} "
            f"| {row.accuracy_when_answering:.1%} |"
        )
    return "\n".join(lines)
