"""Real-channel transfer study: does the harness-calibrated guarantee
survive the actual telephone channel?

Design: seeded scenario manifest mirroring the harness persona joint
distribution exactly (weights, hedge-wrong rate, contradictory
final-statement-truth rate). Each manifest row is one REAL call to the
builder's own consented line; the builder answers from the row's scripted
line, so ground truth is known at dial time. The committed qhat (calibrated
on the seeded harness, never on this data) is applied to each real call's
extraction, and coverage, abstention, and accuracy-when-answering are
reported with Wilson intervals.

Provenance, stated everywhere this data appears: real phone channel,
builder-answered scripted ground truth. Never presented as calls to real
practices.

    uv run python -m eval.study generate   # manifest + printable sheets
    uv run python -m eval.study analyze    # metrics from collected payloads
"""

import json
import random
import sys
from pathlib import Path
from typing import Any

from app.extract import extract_yes_no
from eval.conformal import prediction_set, wilson_interval
from eval.personas import (
    _FINAL_STATEMENT_TRUTH_RATE,
    _HEDGE_WRONG_RATE,
    _WEIGHTS,
    _reply,
)

STUDY_SEED = 20260726
STUDY_N = 36
DATA_DIR = Path(__file__).parent / "study_data"
CALLS_DIR = DATA_DIR / "calls"
RESULTS = Path(__file__).parent / "results" / "real_channel.json"
PROVENANCE = (
    "real phone channel, builder-answered scripted ground truth "
    "(consented builder line; never calls to real practices)"
)


def generate_manifest(n: int = STUDY_N, seed: int = STUDY_SEED) -> dict[str, Any]:
    """Mirror eval.personas.generate's joint distribution for real calls."""
    rng = random.Random(seed)
    names = list(_WEIGHTS)
    weights = [_WEIGHTS[name] for name in names]
    calls: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        persona = rng.choices(names, weights=weights, k=1)[0]
        if persona in {"evasive", "wrong_number", "refuses"}:
            truth = "unknown"
        elif persona == "contradictory":
            truth = "no" if rng.random() < 0.5 else "yes"
        else:
            truth = rng.choice(["yes", "no"])
        line = _reply(rng, persona, truth)
        if persona == "contradictory" and rng.random() > _FINAL_STATEMENT_TRUTH_RATE:
            truth = "no" if truth == "yes" else "yes"
        calls.append(
            {
                "n": i,
                "persona": persona,
                "truth": truth,
                "line": line,
                "status": "pending",
                "calle_call_id": None,
            }
        )
    return {
        "seed": seed,
        "n": n,
        "hedge_wrong_rate": _HEDGE_WRONG_RATE,
        "final_statement_truth_rate": _FINAL_STATEMENT_TRUTH_RATE,
        "provenance": PROVENANCE,
        "calls": calls,
    }


def _sheet(manifest: dict[str, Any]) -> str:
    lines = [
        "# Real-channel study: respondent sheets",
        "",
        f"Seed {manifest['seed']}, {manifest['n']} calls. {PROVENANCE}.",
        "",
        "Per call: answer the bot's question using the scripted line. Deliver",
        "it naturally (your own filler words are fine and wanted); keep the",
        "polarity and behavior of the line. For wrong-number and refusal",
        "lines, act them fully and let the call end.",
        "",
    ]
    for call in manifest["calls"]:
        lines.append(f"## Call {call['n']:>2}  [{call['persona']}]")
        lines.append(f'Say: "{call["line"]}"')
        lines.append("")
    return "\n".join(lines)


def _transcript_turns(payload: dict[str, Any]) -> list[dict[str, object]]:
    for recipient in payload.get("recipients") or []:
        for attempt in recipient.get("attempts") or []:
            turns = attempt.get("transcript_turns")
            if turns:
                return list(turns)
    return []


def analyze(
    manifest_path: Path = DATA_DIR / "manifest.json",
    calls_dir: Path = CALLS_DIR,
    metrics_path: Path = Path(__file__).parent / "results" / "metrics.json",
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text())
    qhat = float(json.loads(metrics_path.read_text())["headline"]["qhat"])

    rows: list[dict[str, Any]] = []
    for call in manifest["calls"]:
        payload_path = calls_dir / f"call_{call['n']:02d}.json"
        if not payload_path.is_file():
            continue
        payload = json.loads(payload_path.read_text())
        turns = _transcript_turns(payload)
        extraction = extract_yes_no(turns)
        pset = prediction_set(extraction.class_scores(), qhat)
        # Mirror the served gate exactly (backend/app/analysis.py).
        abstain = len(pset) != 1 or extraction.answer.value == "unknown"
        rows.append(
            {
                "n": call["n"],
                "persona": call["persona"],
                "truth": call["truth"],
                "answer": extraction.answer.value,
                "abstain": abstain,
                "covered": call["truth"] in pset,
                "set_size": len(pset),
            }
        )

    n = len(rows)
    if n == 0:
        raise SystemExit("no collected calls found; run scripts/study_call.py first")
    covered = sum(1 for r in rows if r["covered"])
    abstained = sum(1 for r in rows if r["abstain"])
    answered = [r for r in rows if not r["abstain"]]
    correct = sum(1 for r in answered if r["answer"] == r["truth"])
    per_persona: dict[str, dict[str, int]] = {}
    for r in rows:
        bucket = per_persona.setdefault(r["persona"], {"n": 0, "covered": 0, "abstained": 0})
        bucket["n"] += 1
        bucket["covered"] += int(r["covered"])
        bucket["abstained"] += int(r["abstain"])

    report = {
        "provenance": PROVENANCE,
        "seed": manifest["seed"],
        "n_collected": n,
        "n_manifest": manifest["n"],
        "qhat_source": "harness-calibrated (metrics.json); never fit on this data",
        "qhat": qhat,
        "empirical_coverage": covered / n,
        "coverage_wilson_95": list(wilson_interval(covered, n)),
        "abstention_rate": abstained / n,
        "accuracy_when_answering": (correct / len(answered)) if answered else None,
        "answering_wilson_95": list(wilson_interval(correct, len(answered))) if answered else None,
        "per_persona": per_persona,
        "rows": rows,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "generate":
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        manifest_path = DATA_DIR / "manifest.json"
        if manifest_path.exists():
            raise SystemExit("manifest.json already exists; refusing to overwrite ground truth")
        manifest = generate_manifest()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        (DATA_DIR / "sheets.md").write_text(_sheet(manifest))
        print(
            f"manifest + sheets written to {DATA_DIR} (n={manifest['n']}, seed={manifest['seed']})"
        )
    elif command == "analyze":
        report = analyze()
        lo, hi = report["coverage_wilson_95"]
        print(f"{PROVENANCE}")
        print(f"n={report['n_collected']} of {report['n_manifest']} planned, qhat={report['qhat']}")
        print(
            f"coverage {report['empirical_coverage']:.1%} "
            f"(95% Wilson [{lo:.1%}, {hi:.1%}]), "
            f"abstention {report['abstention_rate']:.1%}, "
            f"accuracy when answering "
            f"{report['accuracy_when_answering']:.1%}"
            if report["accuracy_when_answering"] is not None
            else "no answered calls"
        )
        print(f"written to {RESULTS}")
    else:
        raise SystemExit("usage: python -m eval.study {generate|analyze}")


if __name__ == "__main__":
    main()
