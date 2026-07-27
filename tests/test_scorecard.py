"""The real-practice scorecard aggregates consented runs to anonymized
counts, and refuses any run without consent on file."""

import json
from pathlib import Path
from typing import Any

import pytest

from eval.scorecard import build_scorecard


def _write(tmp_path: Path, runs: list[dict[str, Any]]) -> Path:
    for entry in runs:
        payload = {"recipients": [{"attempts": [{"transcript_turns": entry.pop("_turns")}]}]}
        (tmp_path / entry["payload"]).write_text(json.dumps(payload))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"runs": runs}))
    return manifest


def test_scorecard_counts_and_anonymizes(tmp_path: Path) -> None:
    yes_turns = [
        {"speaker": "bot", "text": "Is this the office of X?"},
        {"speaker": "user", "text": "Yes, this is."},
        {"speaker": "bot", "text": "Accepting new patients?"},
        {"speaker": "user", "text": "Yes, we are."},
    ]
    manifest = _write(
        tmp_path,
        [
            {
                "label": "a",
                "payload": "a.json",
                "consent_on_file": True,
                "directory_claims": {
                    "office_name_confirmed": "yes",
                    "accepting_new_patients": "yes",
                },
                "_turns": yes_turns,
            }
        ],
    )
    card = build_scorecard(manifest)
    assert card["n_listings"] == 1
    assert set(card["counts"]) == {"verified", "contradicted", "unverifiable"}
    # No practice name or phone anywhere in the card.
    assert "office of X" not in json.dumps(card)


def test_scorecard_refuses_a_run_without_consent(tmp_path: Path) -> None:
    manifest = _write(
        tmp_path,
        [
            {
                "label": "no-consent",
                "payload": "b.json",
                "consent_on_file": False,
                "directory_claims": {},
                "_turns": [],
            }
        ],
    )
    with pytest.raises(SystemExit):
        build_scorecard(manifest)
