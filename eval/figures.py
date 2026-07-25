"""Judge-facing figures. Each must be readable in under ten seconds.

Styling follows the dataviz discipline: one hue per single-series chart, a
neutral dashed reference, recessive grid, ink-colored text, direct labels,
and a provenance caption baked into the image (scripted personas, seed, n).
"""

import matplotlib

matplotlib.use("Agg")

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from eval.conformal import ConformalReport, wilson_interval

_SERIES = "#2563eb"
_REFERENCE = "#9ca3af"
_INK = "#111827"
_MUTED = "#6b7280"
_GRID = "#e5e7eb"


def _style(ax: Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(_GRID)
    ax.tick_params(colors=_MUTED, labelsize=9)
    ax.grid(True, color=_GRID, linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)


def _provenance(fig: Figure, seed: int, n_cal: int, n_test: int) -> None:
    fig.text(
        0.01,
        0.01,
        f"Evaluation harness: scripted adversarial personas. seed={seed}, "
        f"calibration n={n_cal}, held-out test n={n_test}. Disjoint folds.",
        fontsize=7,
        color=_MUTED,
    )


def reliability_diagram(
    reports: list[ConformalReport], seed: int, n_cal: int, out_dir: Path
) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=160)
    targets = [1 - report.alpha for report in reports]
    empirical = [report.coverage for report in reports]
    lows, highs = [], []
    for report in reports:
        low, high = wilson_interval(round(report.coverage * report.n_test), report.n_test)
        lows.append(low)
        highs.append(high)

    ax.plot([0.6, 1.0], [0.6, 1.0], linestyle="--", linewidth=1.2, color=_REFERENCE)
    ax.text(0.965, 0.945, "ideal", fontsize=8, color=_MUTED, ha="right")
    ax.fill_between(targets, lows, highs, color=_SERIES, alpha=0.15, linewidth=0)
    ax.plot(targets, empirical, linewidth=2, color=_SERIES, marker="o", markersize=5)

    ax.set_xlabel("Target coverage (1 - alpha)", color=_INK, fontsize=10)
    ax.set_ylabel("Empirical coverage, held-out fold", color=_INK, fontsize=10)
    ax.set_title(
        "The guarantee holds: empirical coverage tracks the target",
        color=_INK,
        fontsize=11,
        loc="left",
    )
    ax.set_xlim(0.62, 1.0)
    ax.set_ylim(0.62, 1.02)
    _style(ax)
    _provenance(fig, seed, n_cal, reports[0].n_test)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out_dir / "reliability_diagram.png")
    fig.savefig(out_dir / "reliability_diagram.svg")
    plt.close(fig)


def risk_coverage(
    curve: list[tuple[float, float]],
    operating_point: tuple[float, float],
    seed: int,
    n_cal: int,
    n_test: int,
    out_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=160)
    xs = [point[0] for point in curve]
    ys = [point[1] for point in curve]
    ax.plot(xs, ys, linewidth=2, color=_SERIES)
    ax.scatter([operating_point[0]], [operating_point[1]], s=48, color=_INK, zorder=3)
    ax.annotate(
        "Attest operating point\n(abstain instead of guess)",
        xy=operating_point,
        xytext=(operating_point[0] - 0.02, operating_point[1] + 0.08),
        fontsize=8,
        color=_INK,
        ha="right",
        arrowprops={"arrowstyle": "-", "color": _MUTED, "linewidth": 0.8},
    )
    ax.set_xlabel("Fraction of calls answered (coverage)", color=_INK, fontsize=10)
    ax.set_ylabel("Error rate among answered (risk)", color=_INK, fontsize=10)
    ax.set_title(
        "Answering less means being wrong less, measurably",
        color=_INK,
        fontsize=11,
        loc="left",
    )
    ax.set_xlim(0, 1.02)
    ax.set_ylim(0, max(ys) * 1.25 + 0.02)
    _style(ax)
    _provenance(fig, seed, n_cal, n_test)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out_dir / "risk_coverage.png")
    fig.savefig(out_dir / "risk_coverage.svg")
    plt.close(fig)
