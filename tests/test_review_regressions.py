"""Regression pins for the full-repo silent-failure review findings."""

import json
import re
from pathlib import Path

from app.analysis import redact_payload

ROOT = Path(__file__).parent.parent


def test_request_echo_is_stripped_from_served_payloads() -> None:
    """H3: the mock create path stores request.recipient with the raw dialed
    number; redaction must remove it before anything leaves the server."""
    payload = {
        "id": "call_mock_x",
        "recipients": [{"phones": ["+15551234567"], "attempts": [{"phone": "+15551234567"}]}],
        "request": {
            "task": "verify",
            "recipient": {"phones": ["+15551234567"]},
            "metadata": {},
        },
    }
    redacted = redact_payload(payload)
    raw = json.dumps(redacted)
    assert "+15551234567" not in raw
    assert "request" not in redacted


def test_landing_numbers_match_the_canonical_metrics() -> None:
    """L5 guard: the landing hardcodes display numbers; they must agree with
    eval/results/metrics.json or the page silently contradicts the eval."""
    metrics = json.loads((ROOT / "eval" / "results" / "metrics.json").read_text())
    head = metrics["headline"]
    landing = (ROOT / "frontend" / "src" / "experience" / "Landing.tsx").read_text()
    expected = {
        f"{head['empirical_coverage'] * 100:.1f}%",
        f"{head['abstention_rate'] * 100:.1f}%",
        f"{head['accuracy_when_answering'] * 100:.1f}%",
    }
    for token in expected:
        assert token in landing, (
            f"Landing.tsx is missing {token}; regenerate its numbers from metrics.json"
        )


def test_unknown_status_vocabulary_is_logged(caplog) -> None:  # type: ignore[no-untyped-def]
    """H2: a status outside pending+terminal must be loud, not a silent no-op."""
    from app import runs

    with caplog.at_level("WARNING"):
        landed = runs.apply_terminal_payload(
            ROOT / "data" / "nonexistent.db", {"id": "call_x", "status": "expired"}
        )
    assert landed is False
    assert any("unknown CALL-E status" in message for message in caplog.messages)


def test_no_bare_replace_path_derivation_in_skill_scripts() -> None:
    """L1: sibling-script paths derive via Path.with_name, not str.replace."""
    text = (ROOT / "skills" / "verify-by-phone" / "scripts" / "reconcile_record.py").read_text()
    assert "__file__.replace" not in text
    assert re.search(r"with_name\(", text)
