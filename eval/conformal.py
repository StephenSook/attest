"""Split conformal prediction with abstention. The twenty lines that matter.

Implemented directly rather than through a framework so a reviewer can verify
the guarantee in one read: with a calibration fold of size n and miscoverage
level alpha, the prediction set built from the ceil((n+1)(1-alpha))/n quantile
of calibration nonconformity scores contains the true label with probability
at least 1 - alpha on exchangeable data. Delete every hosted AI API from this
repository and this file still runs.
"""

import math
from dataclasses import dataclass

CLASSES = ("yes", "no", "unknown")


def conformal_quantile(cal_nonconformity: list[float], alpha: float) -> float:
    """The finite-sample-corrected (1 - alpha) quantile of calibration scores."""
    if not cal_nonconformity:
        raise ValueError("empty calibration fold")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    ordered = sorted(cal_nonconformity)
    n = len(ordered)
    rank = math.ceil((n + 1) * (1 - alpha))
    if rank > n:
        return float("inf")
    return ordered[rank - 1]


def nonconformity(class_scores: dict[str, float], true_label: str) -> float:
    return 1.0 - class_scores[true_label]


def prediction_set(class_scores: dict[str, float], qhat: float) -> set[str]:
    return {label for label in CLASSES if 1.0 - class_scores[label] <= qhat}


@dataclass(frozen=True)
class ConformalReport:
    alpha: float
    qhat: float
    coverage: float  # P(true label in set) on the held-out fold
    abstention_rate: float  # fraction where |set| != 1
    singleton_accuracy: float  # accuracy among answered (|set| == 1)
    n_test: int


def evaluate_alpha(
    cal_scores: list[tuple[dict[str, float], str]],
    test_scores: list[tuple[dict[str, float], str]],
    alpha: float,
) -> ConformalReport:
    qhat = conformal_quantile([nonconformity(scores, truth) for scores, truth in cal_scores], alpha)
    covered = 0
    singletons = 0
    singleton_correct = 0
    for scores, truth in test_scores:
        pset = prediction_set(scores, qhat)
        if truth in pset:
            covered += 1
        if len(pset) == 1:
            singletons += 1
            if truth in pset:
                singleton_correct += 1
    n = len(test_scores)
    return ConformalReport(
        alpha=alpha,
        qhat=qhat,
        coverage=covered / n,
        abstention_rate=1 - singletons / n,
        singleton_accuracy=(singleton_correct / singletons) if singletons else 1.0,
        n_test=n,
    )


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95 percent Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return (max(0.0, center - margin), min(1.0, center + margin))


def risk_coverage_curve(
    test_points: list[tuple[float, bool]],
) -> list[tuple[float, float]]:
    """Selective-prediction curve: sweep a trust-score threshold and report
    (fraction answered, error rate among answered). test_points are
    (trust_score, is_correct) pairs for forced (non-abstaining) answers.
    """
    ordered = sorted(test_points, key=lambda point: -point[0])
    n = len(ordered)
    curve: list[tuple[float, float]] = []
    errors = 0
    for index, (_, correct) in enumerate(ordered, start=1):
        if not correct:
            errors += 1
        curve.append((index / n, errors / index))
    return curve
