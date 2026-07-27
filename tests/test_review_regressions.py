"""Regression pins for the full-repo silent-failure review findings."""

import json
import re
from pathlib import Path
from typing import Any, cast

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


def test_same_turn_contradiction_trusts_the_later_statement() -> None:
    """Convention review CRITICAL 3: 'yes, actually no' inside one turn must
    resolve to the later polarity, not whichever list max() saw first."""
    from app.extract import extract_yes_no
    from app.models import Answer

    turns: list[dict[str, object]] = [
        {"speaker": "bot", "text": "Are you accepting new patients?"},
        {"speaker": "user", "text": "Yes, well, hold on, actually no, we are not taking anyone."},
    ]
    result = extract_yes_no(turns)
    assert result.answer is Answer.NO
    # And the mirror image resolves to yes.
    turns[1] = {"speaker": "user", "text": "No, wait, actually yes, we are accepting new patients."}
    assert extract_yes_no(turns).answer is Answer.YES


def test_served_abstention_is_the_conformal_gate(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Convention review 4: the served abstain decision applies the committed
    qhat, and the payload says whether calibration was in effect."""
    import sqlite3
    from typing import Any, cast

    from app import analysis

    def fake_row(payload: dict[str, Any]) -> sqlite3.Row:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE r (terminal_payload TEXT, record_json TEXT)")
        conn.execute("INSERT INTO r VALUES (?, ?)", (json.dumps(payload), None))
        return cast(sqlite3.Row, conn.execute("SELECT * FROM r").fetchone())

    payload = {
        "recipients": [
            {
                "attempts": [
                    {
                        "transcript_turns": [
                            {"speaker": "bot", "text": "Are you accepting new patients?"},
                            {"speaker": "user", "text": "Yes, we are accepting new patients."},
                        ]
                    }
                ]
            }
        ]
    }

    # A qhat of 0.99 admits every class into the prediction set: forced abstain.
    strict = tmp_path / "strict.json"
    strict.write_text(json.dumps({"headline": {"qhat": 0.99}}))
    monkeypatch.setenv("ATTEST_METRICS_PATH", str(strict))

    def accepting(doc: dict[str, Any]) -> dict[str, Any]:
        claims = cast(list[dict[str, Any]], doc["claims"])
        return next(c for c in claims if c["claim"] == "accepting_new_patients")

    claim = accepting(analysis.analyze_run(fake_row(payload)))
    assert claim["calibrated"] is True
    assert claim["abstain"] is True
    assert claim["answer"] == "unknown"
    assert claim["stated_answer"] == "yes"

    # The committed qhat admits only the confident class: the answer is served.
    committed = tmp_path / "committed.json"
    committed.write_text(json.dumps({"headline": {"qhat": 0.75}}))
    monkeypatch.setenv("ATTEST_METRICS_PATH", str(committed))
    claim = accepting(analysis.analyze_run(fake_row(payload)))
    assert claim["calibrated"] is True
    assert claim["abstain"] is False
    assert claim["answer"] == "yes"

    # No metrics file: the response is honest that no calibration applied.
    monkeypatch.setenv("ATTEST_METRICS_PATH", str(tmp_path / "missing.json"))
    claim = accepting(analysis.analyze_run(fake_row(payload)))
    assert claim["calibrated"] is False


def test_multi_claim_call_reaches_a_verified_verdict() -> None:
    """Wave N1: three agreeing claims clear the 0.85 verified bar, which a
    single claim mathematically never could (+1.36 bits from even odds)."""
    import sqlite3

    from app import analysis

    def fake_row(payload: dict[str, Any], record: dict[str, Any]) -> sqlite3.Row:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE r (terminal_payload TEXT, record_json TEXT)")
        conn.execute("INSERT INTO r VALUES (?, ?)", (json.dumps(payload), json.dumps(record)))
        return cast(sqlite3.Row, conn.execute("SELECT * FROM r").fetchone())

    payload = {
        "recipients": [
            {
                "attempts": [
                    {
                        "transcript_turns": [
                            {
                                "speaker": "bot",
                                "text": "Is this the office of Example Counseling Center?",
                            },
                            {"speaker": "user", "text": "Yes, this is."},
                            {"speaker": "bot", "text": "Are you accepting new patients?"},
                            {"speaker": "user", "text": "Yes, we are accepting new patients."},
                            {"speaker": "bot", "text": "Do you accept the Aetna plan?"},
                            {"speaker": "user", "text": "Yes, we take that insurance."},
                        ]
                    }
                ]
            }
        ]
    }
    record = {
        "org": "Example Counseling Center",
        "claims": {
            "office_name_confirmed": "yes",
            "accepting_new_patients": "yes",
            "accepts_plan": "yes",
        },
    }
    doc = analysis.analyze_run(fake_row(payload, record))
    answers = {c["claim"]: c["answer"] for c in doc["claims"]}
    assert answers["office_name_confirmed"] == "yes"
    assert answers["accepting_new_patients"] == "yes"
    assert answers["accepts_plan"] == "yes"
    recon = doc["reconciliation"]
    assert recon["verdict"] == "verified"
    assert recon["posterior_probability"] > 0.9
