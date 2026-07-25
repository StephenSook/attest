"""Server-side analysis of terminal payloads for the console.

The browser never computes or submits verdicts: extraction and reconciliation
run here, on the server-stored payload, and the API serves the result.
Phone numbers are redacted before anything leaves the server.
"""

import copy
import json
import sqlite3
from typing import Any

from app.extract import extract_yes_no
from app.models import Answer
from app.reconcile import reconcile

CLAIM_QUESTIONS = {
    "accepting_new_patients": r"accepting new patients",
    "accepts_plan": r"\baccepts?\b|\btakes?\b.*\b(?:plan|insurance)\b|\bin[- ]network\b",
}


def _mask(phone: str) -> str:
    if len(phone) < 7:
        return "***"
    return phone[:3] + "*" * (len(phone) - 6) + phone[-3:]


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Mask every phone number in a terminal payload before serving it."""
    redacted = copy.deepcopy(payload)
    for recipient in redacted.get("recipients", []):
        recipient["phones"] = [_mask(str(p)) for p in recipient.get("phones", [])]
        for attempt in recipient.get("attempts", []):
            if attempt.get("phone"):
                attempt["phone"] = _mask(str(attempt["phone"]))
    # The mock create path stores the original request, which carries the raw
    # dialed number under request.recipient; strip the whole echo rather than
    # chase its shape.
    redacted.pop("request", None)
    return redacted


def transcript_turns(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for recipient in payload.get("recipients", []):
        for attempt in recipient.get("attempts", []):
            turns = attempt.get("transcript_turns")
            if turns:
                return list(turns)
    return []


def analyze_run(row: sqlite3.Row) -> dict[str, Any]:
    """Extraction + reconciliation for one terminal run, server-authoritative."""
    payload = json.loads(str(row["terminal_payload"])) if row["terminal_payload"] else {}
    record: dict[str, Any] = json.loads(str(row["record_json"])) if row["record_json"] else {}
    turns = transcript_turns(payload)

    claims: list[dict[str, Any]] = []
    call_answers: dict[str, Answer] = {}
    for claim, pattern in CLAIM_QUESTIONS.items():
        extraction = extract_yes_no(turns, question_pattern=pattern)
        call_answers[claim] = extraction.answer
        claims.append(
            {
                "claim": claim,
                "answer": extraction.answer.value,
                "trust_score": round(extraction.score, 3),
                "hedged": extraction.hedged,
                "abstain": extraction.answer is Answer.UNKNOWN,
                "span": (
                    {
                        "turn": extraction.span_turn,
                        "text": extraction.span_text,
                        "char_start": extraction.span_char_start,
                        "char_end": extraction.span_char_end,
                    }
                    if extraction.span_turn is not None
                    else None
                ),
            }
        )

    directory_claims = {
        field: Answer(value)
        for field, value in record.get("claims", {}).items()
        if value in {"yes", "no", "unknown"}
    }
    recon = reconcile(call_answers, directory_claims)
    return {
        "org": record.get("org"),
        "replay": bool(record.get("replay", False)),
        "claims": claims,
        "reconciliation": {
            "verdict": recon.verdict,
            "posterior_probability": round(recon.posterior_probability, 4),
            "prior_log_odds": recon.prior_log_odds,
            "posterior_log_odds": round(recon.posterior_log_odds, 4),
            "contributions": [
                {
                    "field": c.field,
                    "call_answer": c.call_answer,
                    "directory_claim": c.directory_claim,
                    "agreed": c.agreed,
                    "weight_bits": round(c.weight_bits, 4),
                }
                for c in recon.contributions
            ],
        },
    }
