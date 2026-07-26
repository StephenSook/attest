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

from app.reconcile import Reconciliation
from eval.conformal import ConformalReport, wilson_interval

_SERIES = "#2563eb"
_REFERENCE = "#9ca3af"
_INK = "#111827"
_MUTED = "#6b7280"
_GRID = "#e5e7eb"
_AGREE = "#2563eb"
_DISAGREE = "#d97706"


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


def match_weight_waterfall(recon: Reconciliation, seed: int, out_dir: Path) -> None:
    """The reconciliation arithmetic, drawn: prior, one bar per field of
    evidence, posterior. Diverging hues: agreement adds blue bits of evidence,
    disagreement subtracts orange ones. Unknowns contribute nothing and say so.
    """
    fig, ax = plt.subplots(figsize=(8.8, 4.6), dpi=160)

    labels = ["prior\n(50/50 audit odds)"]
    steps = [recon.prior_log_odds]
    colors = [_REFERENCE]
    for contribution in recon.contributions:
        pretty = contribution.field.replace("_", " ")
        if contribution.agreed is None:
            labels.append(f"{pretty}\n(no evidence)")
            steps.append(0.0)
            colors.append(_GRID)
        else:
            word = "agrees" if contribution.agreed else "disagrees"
            labels.append(f"{pretty}\n({word})")
            steps.append(contribution.weight_bits)
            colors.append(_AGREE if contribution.agreed else _DISAGREE)

    cumulative = 0.0
    for index, (step, color) in enumerate(zip(steps, colors, strict=True)):
        ax.bar(index, step, bottom=cumulative, width=0.55, color=color, zorder=3)
        cumulative += step
        if index < len(steps) - 1:
            ax.plot(
                [index + 0.28, index + 0.72],
                [cumulative, cumulative],
                color=_MUTED,
                linewidth=0.8,
                zorder=2,
            )
        if abs(step) > 0.01:
            ax.text(
                index,
                cumulative + (0.12 if step >= 0 else -0.22),
                f"{step:+.2f}",
                ha="center",
                fontsize=8,
                color=_INK,
            )

    final_index = len(steps)
    ax.bar(final_index, cumulative, width=0.55, color=_INK, zorder=3)
    ax.text(
        final_index,
        cumulative + 0.12,
        f"{recon.posterior_probability:.0%} accurate\n{recon.verdict.upper()}",
        ha="center",
        fontsize=8,
        color=_INK,
    )
    labels.append("posterior")

    ax.axhline(0, color=_GRID, linewidth=0.8)
    top = max(cumulative, max(steps, default=0.0)) + 1.1
    bottom = min(0.0, cumulative) - 0.4
    ax.set_ylim(bottom, top)
    ax.set_xticks(range(len(labels)), labels, fontsize=7.5, color=_INK)
    ax.set_ylabel("Match weight (bits of evidence)", color=_INK, fontsize=10)
    ax.set_title(
        "Why this listing was believed: the match-weight arithmetic",
        color=_INK,
        fontsize=11,
        loc="left",
    )
    _style(ax)
    fig.text(
        0.01,
        0.01,
        f"Fellegi-Sunter reconciliation, fixed documented m/u priors. "
        f"Harness scenario, seed={seed}.",
        fontsize=7,
        color=_MUTED,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(out_dir / "match_weight_waterfall.png")
    fig.savefig(out_dir / "match_weight_waterfall.svg")
    plt.close(fig)


def calibration_sensitivity_figure(
    rows: list[dict[str, float]], alpha: float, seed: int, n_test: int, out_dir: Path
) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=160)
    sizes = [row["n_cal"] for row in rows]
    coverages = [row["coverage"] for row in rows]
    lows, highs = [], []
    for row in rows:
        low, high = wilson_interval(round(row["coverage"] * n_test), n_test)
        lows.append(low)
        highs.append(high)
    target = 1 - alpha
    ax.axhline(target, linestyle="--", linewidth=1.2, color=_REFERENCE)
    ax.text(sizes[-1], target + 0.004, f"target {target:.0%}", fontsize=8, color=_MUTED, ha="right")
    ax.fill_between(sizes, lows, highs, color=_SERIES, alpha=0.15, linewidth=0)
    ax.plot(sizes, coverages, linewidth=2, color=_SERIES, marker="o", markersize=5)
    ax.set_xlabel("Calibration fold size", color=_INK, fontsize=10)
    ax.set_ylabel("Coverage on the full held-out fold", color=_INK, fontsize=10)
    ax.set_title(
        "How much calibration data the guarantee needs",
        color=_INK,
        fontsize=11,
        loc="left",
    )
    ax.set_ylim(min(lows) - 0.02, 1.005)
    _style(ax)
    _provenance(fig, seed, int(sizes[-1]), n_test)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out_dir / "calibration_sensitivity.png")
    fig.savefig(out_dir / "calibration_sensitivity.svg")
    plt.close(fig)
