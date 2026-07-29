"""Anonymized real-practice verification scorecard.

Aggregates verification outcomes across CONSENTED real-practice runs into
one anonymized table: n listings verified, how many the call confirmed,
contradicted, or honestly abstained on. No practice names, no phone
numbers, no transcripts: counts only, per the operator-unassociation
principle for defender-side tooling.

Input: a consent manifest listing run payload files that each carry
written per-surface consent, plus the directory claims each call verified.

    uv run python -m eval.scorecard <path/to/manifest.json>

No manifest is committed: it names real consented practices, so it stays out
of the repository along with the payloads it points at.
"""

import json
import sys
from pathlib import Path
from typing import Any

from app.analysis import CLAIM_QUESTIONS, transcript_turns
from app.extract import extract_yes_no
from app.models import Answer
from app.reconcile import reconcile


def build_scorecard(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text())
    rows: list[dict[str, Any]] = []
    for entry in manifest["runs"]:
        if entry.get("consent_on_file") is not True:
            raise SystemExit(f"run {entry.get('label', '?')} lacks consent_on_file=true; refusing")
        payload = json.loads((manifest_path.parent / entry["payload"]).read_text())
        turns = transcript_turns(payload)
        # Same window bounding as the served path: these are real multi-question
        # calls, so a later answer must not be credited to an earlier claim.
        call_answers = {
            claim: extract_yes_no(
                turns,
                question_pattern=pattern,
                other_question_patterns=tuple(
                    p for name, p in CLAIM_QUESTIONS.items() if name != claim
                ),
            ).answer
            for claim, pattern in CLAIM_QUESTIONS.items()
        }
        directory_claims = {
            claim: Answer(value) for claim, value in entry.get("directory_claims", {}).items()
        }
        recon = reconcile(call_answers=call_answers, directory_claims=directory_claims)
        rows.append({"verdict": recon.verdict})

    n = len(rows)
    counts = {
        "verified": sum(1 for r in rows if r["verdict"] == "verified"),
        "contradicted": sum(1 for r in rows if r["verdict"] == "contradicted"),
        "unverifiable": sum(1 for r in rows if r["verdict"] == "unverifiable"),
    }
    return {
        "n_listings": n,
        "counts": counts,
        "provenance": (
            "real consented practice verifications, anonymized to counts; "
            "per-surface written consent on file for every run"
        ),
    }


def as_markdown(card: dict[str, Any]) -> str:
    c = card["counts"]
    return (
        f"| Listings verified | Confirmed | Contradicted | Could not establish |\n"
        f"| --- | --- | --- | --- |\n"
        f"| {card['n_listings']} | {c['verified']} "
        f"| {c['contradicted']} | {c['unverifiable']} |\n\n"
        f"_{card['provenance']}_"
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m eval.scorecard <manifest.json>")
    card = build_scorecard(Path(sys.argv[1]))
    print(as_markdown(card))


if __name__ == "__main__":
    main()
