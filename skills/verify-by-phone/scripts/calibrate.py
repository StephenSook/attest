#!/usr/bin/env python3
"""Calibrate the abstention threshold with split conformal prediction.

Standard library only, no credentials, no calls: runs on labeled scenario
data (see references/sample-scenarios.jsonl). Split conformal with the
finite-sample correction: with calibration size n and miscoverage alpha, the
prediction set built from the ceil((n+1)(1-alpha))/n quantile of calibration
nonconformity scores contains the true label with probability at least
1 - alpha on held-out exchangeable data. Abstain when the set is not a
single value. That is the entire guarantee, and you can read it right here.
"""

import argparse
import json
import math

CLASSES = ("yes", "no", "unknown")


def class_scores(answer: str, trust: float) -> dict[str, float]:
    if answer == "unknown":
        return {"yes": (1 - trust) / 2, "no": (1 - trust) / 2, "unknown": trust}
    other = 1 - trust
    scores = {"yes": other * 0.4, "no": other * 0.4, "unknown": other * 0.6}
    scores[answer] = trust
    return scores


def quantile(values: list[float], alpha: float) -> float:
    ordered = sorted(values)
    rank = math.ceil((len(ordered) + 1) * (1 - alpha))
    return float("inf") if rank > len(ordered) else ordered[rank - 1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="JSONL: answer, trust_score, truth")
    parser.add_argument("--alpha", type=float, default=0.1)
    args = parser.parse_args()

    rows = []
    with open(args.data, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    half = len(rows) // 2
    calibration, test = rows[:half], rows[half:]
    if not calibration or not test:
        raise SystemExit("ERROR: need at least two labeled rows to calibrate.")

    cal_scores = [
        1.0 - class_scores(row["answer"], row["trust_score"])[row["truth"]] for row in calibration
    ]
    qhat = quantile(cal_scores, args.alpha)

    covered = singletons = singleton_correct = 0
    for row in test:
        scores = class_scores(row["answer"], row["trust_score"])
        pset = {label for label in CLASSES if 1.0 - scores[label] <= qhat}
        if row["truth"] in pset:
            covered += 1
        if len(pset) == 1:
            singletons += 1
            if row["truth"] in pset:
                singleton_correct += 1

    n = len(test)
    print(f"calibration n={len(calibration)}, held-out test n={n} (disjoint)")
    print(f"alpha={args.alpha}: qhat={qhat:.3f}")
    print(f"empirical coverage: {covered / n:.1%} (target {1 - args.alpha:.0%})")
    print(f"abstention rate: {1 - singletons / n:.1%}")
    if singletons:
        print(f"accuracy when answering: {singleton_correct / singletons:.1%}")


if __name__ == "__main__":
    main()
