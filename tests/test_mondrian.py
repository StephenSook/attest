"""Class-conditional (Mondrian) conformal and calibration sensitivity.

The point of Mondrian here is empirical and honest: on this harness the
marginal gate under-covers the "no" class while over-covering "unknown";
per-class thresholds close most of that gap. These tests pin the math, not
the narrative.
"""

from app.extract import extract_yes_no
from eval.conformal import (
    CLASSES,
    calibration_sensitivity,
    evaluate_mondrian,
    mondrian_prediction_set,
    mondrian_qhats,
)
from eval.personas import generate

ALPHA = 0.10


def _pairs(n: int, seed: int) -> list[tuple[dict[str, float], str]]:
    return [
        (extract_yes_no(s.transcript_turns).class_scores(), s.truth) for s in generate(n, seed=seed)
    ]


def test_mondrian_thresholds_cover_every_class() -> None:
    cal = _pairs(300, seed=1)
    test = _pairs(300, seed=2)
    qhats, per_class, overall = evaluate_mondrian(cal, test, ALPHA)
    assert set(qhats) == set(CLASSES)
    assert overall >= 1 - ALPHA - 0.05
    for row in per_class:
        # The class-conditional guarantee is per-class 1 - alpha in
        # expectation; allow finite-sample slack on a 300-point fold.
        assert row.mondrian_coverage >= 1 - ALPHA - 0.08, (
            f"{row.label} under-covered under the Mondrian gate"
        )


def test_mondrian_set_uses_per_class_thresholds() -> None:
    qhats = {"yes": 0.9, "no": 0.0, "unknown": 0.0}
    scores = {"yes": 0.5, "no": 0.5, "unknown": 0.5}
    # yes admits at a loose threshold; the tight thresholds exclude the rest.
    assert mondrian_prediction_set(scores, qhats) == {"yes"}


def test_mondrian_qhats_infinite_for_absent_class() -> None:
    cal = [({"yes": 0.9, "no": 0.05, "unknown": 0.05}, "yes")] * 30
    qhats = mondrian_qhats(cal, ALPHA)
    assert qhats["no"] == float("inf")
    # An infinite threshold admits the class into every set: the honest
    # behavior when calibration has never seen it.
    assert "no" in mondrian_prediction_set({"yes": 0.1, "no": 0.1, "unknown": 0.1}, qhats)


def test_calibration_sensitivity_rows() -> None:
    cal = _pairs(300, seed=3)
    test = _pairs(200, seed=4)
    rows = calibration_sensitivity(cal, test, ALPHA, sizes=(50, 150, 300), seed=9)
    assert [row["n_cal"] for row in rows] == [50, 150, 300]
    for row in rows:
        assert 0.8 <= row["coverage"] <= 1.0
        assert 0.0 <= row["abstention_rate"] <= 1.0
    # Deterministic under the same seed.
    assert rows == calibration_sensitivity(cal, test, ALPHA, sizes=(50, 150, 300), seed=9)
