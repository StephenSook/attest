"""One command regenerates every reported number and figure.

    uv run python -m eval

Fixed seed, disjoint calibration and test folds, intervals not bare points.
Nothing in the README is hand-typed; it all comes from eval/results/.
"""

import json
import os
from pathlib import Path

from app.extract import ExtractionResult, extract_yes_no
from eval.conformal import evaluate_alpha, risk_coverage_curve, wilson_interval
from eval.figures import reliability_diagram, risk_coverage
from eval.personas import Scenario, generate

SEED = 20260725
DEFAULT_N = 600
ALPHAS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
HEADLINE_ALPHA = 0.10


def main() -> None:
    n = int(os.environ.get("ATTEST_EVAL_N", str(DEFAULT_N)))
    out_dir = Path(os.environ.get("ATTEST_EVAL_OUT", "eval/results"))
    out_dir.mkdir(parents=True, exist_ok=True)

    scenarios = generate(n, seed=SEED)
    half = n // 2
    calibration, test = scenarios[:half], scenarios[half:]
    assert not {id(s) for s in calibration} & {id(s) for s in test}

    def scored(
        fold: list[Scenario],
    ) -> list[tuple[dict[str, float], str, ExtractionResult]]:
        pairs: list[tuple[dict[str, float], str, ExtractionResult]] = []
        for scenario in fold:
            extraction = extract_yes_no(scenario.transcript_turns)
            pairs.append((extraction.class_scores(), scenario.truth, extraction))
        return pairs

    cal_pairs = [(scores, truth) for scores, truth, _ in scored(calibration)]
    test_scored = scored(test)
    test_pairs = [(scores, truth) for scores, truth, _ in test_scored]

    reports = [evaluate_alpha(cal_pairs, test_pairs, alpha) for alpha in ALPHAS]
    headline = next(report for report in reports if report.alpha == HEADLINE_ALPHA)

    forced_points = [
        (extraction.score, extraction.answer.value == truth) for _, truth, extraction in test_scored
    ]
    curve = risk_coverage_curve(forced_points)
    answered_fraction = 1 - headline.abstention_rate
    operating = min(curve, key=lambda point: abs(point[0] - answered_fraction))

    reliability_diagram(reports, SEED, len(calibration), out_dir)
    risk_coverage(curve, operating, SEED, len(calibration), len(test), out_dir)

    covered = round(headline.coverage * headline.n_test)
    low, high = wilson_interval(covered, headline.n_test)
    metrics = {
        "seed": SEED,
        "n_total": n,
        "n_calibration": len(calibration),
        "n_test": len(test),
        "personas": "cooperative, hedging, contradictory, evasive, wrong_number, refuses",
        "headline": {
            "alpha": HEADLINE_ALPHA,
            "target_coverage": 1 - HEADLINE_ALPHA,
            "empirical_coverage": headline.coverage,
            "coverage_wilson_95": [low, high],
            "abstention_rate": headline.abstention_rate,
            "accuracy_when_answering": headline.singleton_accuracy,
        },
        "per_alpha": [
            {
                "alpha": report.alpha,
                "target": 1 - report.alpha,
                "empirical_coverage": report.coverage,
                "abstention_rate": report.abstention_rate,
                "accuracy_when_answering": report.singleton_accuracy,
            }
            for report in reports
        ],
        "provenance": "scripted seeded personas; disjoint folds; never presented as real calls",
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    print(f"seed={SEED} n={n} (cal {len(calibration)} / test {len(test)}, disjoint)")
    print(
        f"alpha={HEADLINE_ALPHA}: target {1 - HEADLINE_ALPHA:.0%}, "
        f"empirical coverage {headline.coverage:.1%} "
        f"(95% Wilson [{low:.1%}, {high:.1%}])"
    )
    print(
        f"abstention rate {headline.abstention_rate:.1%}, "
        f"accuracy when answering {headline.singleton_accuracy:.1%}"
    )
    print(f"figures + metrics written to {out_dir}/")


if __name__ == "__main__":
    main()
