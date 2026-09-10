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


def test_redaction_covers_unexpected_phone_locations_without_mutating_input() -> None:
    payload = {
        "recipients": {
            "+15550101234": {
                "attempts": [
                    {
                        "transcript_turns": [
                            {
                                "speaker": "user",
                                "text": (
                                    "Call 555-1234, 612 34 56 78, 5550101234x89, or 555/010/1234."
                                ),
                            }
                        ]
                    }
                ]
            }
        },
        "metadata": {
            "timestamp": "2026-09-10 01:17:24",
            "ip": "192.168.100.123",
            "correlation_id": "1234567890",
            "decimal": "15550101234.0",
            "unknown_number": 15550101234,
            "items": [15550101234.0],
            "notes": ["Call +15550101234", {"detail": "Use 555-1234"}],
        },
    }
    original = json.loads(json.dumps(payload))

    redacted = redact_payload(payload)

    serialized = json.dumps(redacted)
    for phone in ["+15550101234", "555-1234", "612 34 56 78", "5550101234x89", "555/010/1234"]:
        assert phone not in serialized
    assert redacted["metadata"] == {
        "timestamp": "2026-09-10 01:17:24",
        "ip": "192.168.100.123",
        "correlation_id": "[redacted phone]",
        "decimal": "[redacted phone]",
        "unknown_number": "[redacted phone]",
        "items": ["[redacted phone]"],
        "notes": ["Call [redacted phone]", {"detail": "Use [redacted phone]"}],
    }
    assert payload == original


def test_redacted_container_keys_never_collide() -> None:
    for recipients in [
        {"+15550101234": {"marker": "phone"}, "recipient-0": {"marker": "existing"}},
        {"recipient-0": {"marker": "existing"}, "+15550101234": {"marker": "phone"}},
    ]:
        redacted = redact_payload({"recipients": recipients})
        assert len(redacted["recipients"]) == 2
        assert redacted["recipients"]["recipient-0"] == {"marker": "existing"}
        assert "+15550101234" not in redacted["recipients"]
        assert {item["marker"] for item in redacted["recipients"].values()} == {
            "phone",
            "existing",
        }


def test_redaction_handles_schema_drift_without_discarding_safe_provider_ids() -> None:
    payload = {
        "summary": {
            "text": "Call +15550101234 for the result.",
            "provider_id": 42,
            "phone_shaped_id": "+15550101234",
            "id": "12/34/5678",
            "date_shaped_id": "12/34/5678",
            "nested_id": {"value": "+15550101234"},
        },
        "recipients": {
            "rcp_421c14316e95fb62": {
                "phone": {
                    "+15550101234": "primary",
                    "12/34/5678": "secondary",
                },
                "attempts": {
                    "att_74b5e3e66d7ec8d7": {
                        "summary": "Retry at 555-1234.",
                        "failure_message": [
                            {
                                "text": "Escalate through 612 34 56 78.",
                                "provider_id": "550e8400-e29b-41d4-a716-446655440000",
                            }
                        ],
                        "transcript_turns": "Call 555/010/1234.",
                    }
                },
            }
        },
    }

    redacted = redact_payload(payload)
    serialized = json.dumps(redacted)

    for phone in [
        "+15550101234",
        "12/34/5678",
        "555-1234",
        "612 34 56 78",
        "555/010/1234",
    ]:
        assert phone not in serialized
    assert "rcp_421c14316e95fb62" in redacted["recipients"]
    assert "att_74b5e3e66d7ec8d7" in redacted["recipients"]["rcp_421c14316e95fb62"]["attempts"]
    assert redacted["summary"]["provider_id"] == 42
    assert (
        redacted["recipients"]["rcp_421c14316e95fb62"]["attempts"]["att_74b5e3e66d7ec8d7"][
            "failure_message"
        ][0]["provider_id"]
        == "550e8400-e29b-41d4-a716-446655440000"
    )


def test_redaction_rejects_date_shaped_structural_identifiers() -> None:
    payload = {
        "id": "12/34/5678",
        "call_id": "2099-12-31",
        "callId": "12/34/5678",
        "safe_id": "550e8400-e29b-41d4-a716-446655440000",
        "recipients": [
            {
                "recipientId": "12/34/5678",
                "12/34/5678": "recipient-key",
                "attempts": [
                    {
                        "call-id": "2099-12-31",
                        "2099-12-31": "attempt-key",
                        "transcript_turns": [
                            {
                                "turnID": "12/34/5678",
                                "12/34/5678": "turn-key",
                                "text": "Meeting scheduled.",
                            }
                        ],
                    }
                ],
            }
        ],
    }

    redacted = redact_payload(payload)

    assert redacted["id"] == "[redacted phone]"
    assert redacted["call_id"] == "[redacted phone]"
    assert redacted["callId"] == "[redacted phone]"
    assert redacted["safe_id"] == "550e8400-e29b-41d4-a716-446655440000"
    recipient = redacted["recipients"][0]
    assert recipient["recipientId"] == "[redacted phone]"
    assert "12/34/5678" not in recipient
    attempt = recipient["attempts"][0]
    assert attempt["call-id"] == "[redacted phone]"
    assert "2099-12-31" not in attempt
    turn = attempt["transcript_turns"][0]
    assert turn["turnID"] == "[redacted phone]"
    assert "12/34/5678" not in turn


def test_identifier_redaction_handles_plural_prefixed_and_nested_values() -> None:
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    payload = {
        "recipient_ids": ["12/34/5678", uuid],
        "recipient-ids": {"2099-12-31": "tel_15550101234", uuid: uuid},
        "recipientIds": ["acct15550101234", uuid],
        "recipientIDs": ["acctA15550101234B", uuid],
        "recipientIDS": ["call_x15550101234aaaaaaaaaa", uuid],
        "RECIPIENTIDS": {"2099-12-31": "acctB15550101234C", uuid: uuid},
        "recipientids": ["acct15550101234", uuid],
        "recipientID": "acct155.50.101.234x",
        "provider.id": "acctD15550101234E",
        "provider_id_v2": "acctE15550101234F",
        "destinationIdValue": "acctF15550101234G",
        "idList": ["acctG15550101234H"],
        "nested_id": {"value": uuid, "values": [uuid]},
        "provider_ids": [
            "call_FBUuJrnuqAADyQ4d0gBc9Q",
            "rcp_421c14316e95fb62",
            "att_74b5e3e66d7ec8d7",
            "rcp_15550101234",
            "rcp_15550101234a",
            "call_x15550101234aaaaaaaaaa",
        ],
    }

    redacted = redact_payload(payload)
    serialized = json.dumps(redacted)

    for phone in [
        "12/34/5678",
        "2099-12-31",
        "tel_15550101234",
        "acct15550101234",
        "acctA15550101234B",
        "acctB15550101234C",
        "rcp_15550101234",
        "rcp_15550101234a",
        "call_x15550101234aaaaaaaaaa",
        "acct155.50.101.234x",
        "acctD15550101234E",
        "acctE15550101234F",
        "acctF15550101234G",
        "acctG15550101234H",
    ]:
        assert phone not in serialized
    assert serialized.count(uuid) == 11
    assert redacted["provider_ids"][:3] == [
        "call_FBUuJrnuqAADyQ4d0gBc9Q",
        "rcp_421c14316e95fb62",
        "att_74b5e3e66d7ec8d7",
    ]


def test_redaction_sanitizes_phone_mapping_keys_under_unknown_containers() -> None:
    payload = {
        "+15550101234": "root",
        "192.168.100.123": "generic-ip",
        "results": {
            "+15550101234": "nested",
            "acct15550101234": "embedded",
            "acct155.50.101.234x": "dotted-embedded",
            "2099-12-31": "generic-date",
            "2026-09-10T01:17:24Z": "seconds",
            "2026-09-10T01:17:24.123456Z": "fraction",
            "2026-09-10T01:17:24-04:00": "offset",
        },
    }

    redacted = redact_payload(payload)
    serialized = json.dumps(redacted)

    assert "+15550101234" not in serialized
    assert "acct15550101234" not in serialized
    assert "acct155.50.101.234x" not in serialized
    assert "192.168.100.123" not in redacted
    assert redacted["results"]["2099-12-31"] == "generic-date"
    assert redacted["results"]["2026-09-10T01:17:24Z"] == "seconds"
    assert redacted["results"]["2026-09-10T01:17:24.123456Z"] == "fraction"
    assert redacted["results"]["2026-09-10T01:17:24-04:00"] == "offset"
    assert set(redacted) == {"field-0", "field-1", "results"}


def test_redaction_covers_error_text_and_sensitive_mapping_keys() -> None:
    payload = {
        "error": "Could not call +15550101234, 12/34/5678, or 155.50.101.234",
        "recipients": {
            "rcp_421c14316e95fb62": {
                "acct15550101234": "recipient-key",
                "attempts": {
                    "att_74b5e3e66d7ec8d7": {
                        "acct15550101234": "attempt-key",
                        "transcript_turns": [
                            {"acct15550101234": "turn-key", "text": "No phone here."}
                        ],
                    }
                },
            }
        },
    }

    redacted = redact_payload(payload)
    serialized = json.dumps(redacted)

    assert "+15550101234" not in serialized
    assert "12/34/5678" not in serialized
    assert "155.50.101.234" not in serialized
    assert "acct15550101234" not in serialized
    assert redacted["error"] == (
        "Could not call [redacted phone], [redacted phone], or [redacted phone]"
    )


def test_redaction_rejects_phone_data_in_malformed_scalar_containers() -> None:
    payloads: list[dict[str, Any]] = [
        {"recipients": "+15550101234"},
        {"recipients": "12/34/5678"},
        {"recipients": [{"attempts": "+15550101234"}]},
        {"recipients": [{"attempts": [{"transcript_turns": "+15550101234"}]}]},
    ]

    for payload in payloads:
        redacted = json.dumps(redact_payload(payload))
        assert "+15550101234" not in redacted
        assert "12/34/5678" not in redacted

    assert redact_payload({"recipients": "rcp_421c14316e95fb62"}) == {
        "recipients": "rcp_421c14316e95fb62"
    }
    assert redact_payload({"recipients": False}) == {"recipients": False}


def test_analyze_run_ignores_malformed_transcript_members(tmp_path: Path, monkeypatch: Any) -> None:
    import sqlite3

    from app import analysis

    payload = {
        "recipients": [
            {
                "attempts": [
                    {
                        "transcript_turns": [
                            None,
                            "not a turn",
                            {"speaker": "bot", "text": "Are you accepting new patients?"},
                            17,
                            {"speaker": "user", "text": "Yes"},
                        ]
                    }
                ]
            }
        ]
    }
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE r (terminal_payload TEXT, record_json TEXT)")
    conn.execute("INSERT INTO r VALUES (?, ?)", (json.dumps(payload), None))
    row = cast(sqlite3.Row, conn.execute("SELECT * FROM r").fetchone())
    monkeypatch.setenv("ATTEST_METRICS_PATH", str(tmp_path / "missing.json"))

    result = analysis.analyze_run(row)

    claims = cast(list[dict[str, Any]], result["claims"])
    accepting = next(claim for claim in claims if claim["claim"] == "accepting_new_patients")
    assert accepting["stated_answer"] == "yes"
    conn.close()


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


def test_landing_and_prompt_pages_agree_with_metrics() -> None:
    """Both hand-typed surfaces must match the regenerated metrics; the
    landing published a 31-point-wrong abstention rate when the harness gate
    and the served gate had silently diverged."""
    metrics = json.loads((ROOT / "eval" / "results" / "metrics.json").read_text())
    head = metrics["headline"]
    expected = {
        f"{head['empirical_coverage'] * 100:.1f}%",
        f"{head['abstention_rate'] * 100:.1f}%",
        f"{head['accuracy_when_answering'] * 100:.1f}%",
    }
    for page in ("experience/Landing.tsx", "pages/PromptPage.tsx"):
        text = (ROOT / "frontend" / "src" / page).read_text()
        for token in expected:
            assert token in text, f"{page} is missing {token}; regenerate from metrics.json"
