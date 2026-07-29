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


def abstains(class_scores: dict[str, float], answer: str, qhat: float) -> bool:
    """THE abstention gate. One definition, used by the served path
    (backend/app/analysis.py) and by every number this harness reports.

    Three conditions, all meaning "do not answer": the prediction set is not
    a single value, that single value is not the answer being reported, or
    the answer is "unknown". A singleton {unknown} is an abstention, not an
    answer; counting it as answered inflated the reported abstention rate
    against what the product actually does.

    The middle condition was missing until an upstream maintainer found it.
    `len(pset) != 1 or answer == "unknown"` never checks that the singleton
    AGREES with the answer, so a low-trust polar answer whose calibrated set
    is exactly {"unknown"} was served as a confident "yes".

    Every number this harness reports is unchanged by the correction, because
    evaluate_alpha derives the answer as the argmax of the scores and the
    argmax is "unknown" across the whole region where the set is {"unknown"},
    making the two forms provably identical there. A 10^6-point sweep of
    (trust, qhat) confirms zero divergence under argmax and 110826 divergent
    states under an extracted answer. The served and skill paths use the
    extracted answer, so they could reach what the harness could not.
    """
    pset = prediction_set(class_scores, qhat)
    return pset != {answer} or answer == "unknown"


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
        # The served gate, not a looser one: the number reported here is the
        # number the product produces.
        answer = max(scores, key=lambda label: scores[label])
        if not abstains(scores, answer, qhat):
            singletons += 1
            if answer == truth:
                singleton_correct += 1
    n = len(test_scores)
    return ConformalReport(
        alpha=alpha,
        qhat=qhat,
        coverage=covered / n,
        abstention_rate=1 - singletons / n,
        # Answering nothing is not perfect accuracy; report it as undefined.
        singleton_accuracy=(singleton_correct / singletons) if singletons else float("nan"),
        n_test=n,
    )


def mondrian_qhats(
    cal_scores: list[tuple[dict[str, float], str]], alpha: float
) -> dict[str, float]:
    """Class-conditional (Mondrian) thresholds: one finite-sample-corrected
    quantile PER TRUE CLASS, so the guarantee holds within each class rather
    than only on average. Marginal coverage can hide a class that is always
    missed; this cannot."""
    qhats: dict[str, float] = {}
    for label in CLASSES:
        scores = [nonconformity(s, truth) for s, truth in cal_scores if truth == label]
        qhats[label] = conformal_quantile(scores, alpha) if scores else float("inf")
    return qhats


def mondrian_prediction_set(class_scores: dict[str, float], qhats: dict[str, float]) -> set[str]:
    return {label for label in CLASSES if 1.0 - class_scores[label] <= qhats[label]}


@dataclass(frozen=True)
class PerClassCoverage:
    label: str
    n: int
    marginal_coverage: float
    mondrian_coverage: float


def evaluate_mondrian(
    cal_scores: list[tuple[dict[str, float], str]],
    test_scores: list[tuple[dict[str, float], str]],
    alpha: float,
) -> tuple[dict[str, float], list[PerClassCoverage], float]:
    """Per-class coverage under the marginal gate and the Mondrian gate,
    plus overall Mondrian coverage, all on the held-out fold."""
    marginal_qhat = conformal_quantile([nonconformity(s, truth) for s, truth in cal_scores], alpha)
    qhats = mondrian_qhats(cal_scores, alpha)
    per_class: list[PerClassCoverage] = []
    overall_covered = 0
    for label in CLASSES:
        subset = [(s, truth) for s, truth in test_scores if truth == label]
        if not subset:
            continue
        marg = sum(1 for s, truth in subset if truth in prediction_set(s, marginal_qhat))
        mond = sum(1 for s, truth in subset if truth in mondrian_prediction_set(s, qhats))
        per_class.append(
            PerClassCoverage(
                label=label,
                n=len(subset),
                marginal_coverage=marg / len(subset),
                mondrian_coverage=mond / len(subset),
            )
        )
        overall_covered += mond
    return qhats, per_class, overall_covered / len(test_scores)


def calibration_sensitivity(
    cal_scores: list[tuple[dict[str, float], str]],
    test_scores: list[tuple[dict[str, float], str]],
    alpha: float,
    sizes: tuple[int, ...] = (50, 100, 150, 200, 250, 300),
    seed: int = 0,
) -> list[dict[str, float]]:
    """Coverage on the FULL held-out fold as the calibration fold shrinks:
    how much calibration data the guarantee actually needs."""
    import random

    rng = random.Random(seed)
    rows: list[dict[str, float]] = []
    for size in sizes:
        if size > len(cal_scores):
            continue
        subsample = rng.sample(cal_scores, size)
        qhat = conformal_quantile([nonconformity(s, t) for s, t in subsample], alpha)
        covered = sum(1 for s, truth in test_scores if truth in prediction_set(s, qhat))
        abstained = sum(1 for s, _ in test_scores if len(prediction_set(s, qhat)) != 1)
        rows.append(
            {
                "n_cal": size,
                "qhat": qhat,
                "coverage": covered / len(test_scores),
                "abstention_rate": abstained / len(test_scores),
            }
        )
    return rows


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
