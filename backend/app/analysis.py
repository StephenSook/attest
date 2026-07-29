"""Server-side analysis of terminal payloads for the console.

The browser never computes or submits verdicts: extraction and reconciliation
run here, on the server-stored payload, and the API serves the result.
Phone numbers are redacted before anything leaves the server.
"""

import copy
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from app.extract import extract_yes_no
from app.models import Answer
from app.reconcile import reconcile
from eval.conformal import abstains

CLAIM_QUESTIONS = {
    "office_name_confirmed": (
        r"have i reached|am i speaking with"
        r"|is this the office|is this .*(?:office|practice|center|clinic)"
    ),
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
    """Find the transcript in a terminal payload.

    `or []` rather than a default, because the API sends an explicit null for
    a list it has no value for, and a default only covers the absent key. The
    served path raised TypeError on a payload carrying "recipients": null.
    """
    for recipient in payload.get("recipients") or []:
        for attempt in recipient.get("attempts") or []:
            turns = attempt.get("transcript_turns")
            if turns:
                return list(turns)
    return []


def _calibrated_qhat() -> float | None:
    """The conformal threshold from the committed eval run, if present."""
    metrics_path = Path(os.environ.get("ATTEST_METRICS_PATH", "eval/results/metrics.json"))
    try:
        headline = json.loads(metrics_path.read_text())["headline"]
        return float(headline["qhat"])
    except (OSError, KeyError, ValueError, TypeError):
        # Silence here would switch off the conformal guarantee, the whole
        # differentiated claim, with nothing anywhere saying so.
        logging.getLogger(__name__).error(
            "no calibrated qhat at %s; serving UNCALIBRATED extraction decisions",
            metrics_path.resolve(),
        )
        return None


def analyze_run(row: sqlite3.Row) -> dict[str, Any]:
    """Extraction + reconciliation for one terminal run, server-authoritative.

    Abstention is the calibrated conformal decision: answer only when the
    prediction set at the committed qhat is a single value. Without a
    committed eval run the response says so instead of pretending.
    """
    payload = json.loads(str(row["terminal_payload"])) if row["terminal_payload"] else {}
    record: dict[str, Any] = json.loads(str(row["record_json"])) if row["record_json"] else {}
    turns = transcript_turns(payload)

    qhat = _calibrated_qhat()
    claims: list[dict[str, Any]] = []
    call_answers: dict[str, Answer] = {}
    for claim, pattern in CLAIM_QUESTIONS.items():
        # Every other tracked question bounds this claim's answer window. A run
        # asks several questions in one call, so without this an answer given
        # to a later question was also credited to an earlier claim.
        others = tuple(p for name, p in CLAIM_QUESTIONS.items() if name != claim)
        extraction = extract_yes_no(turns, question_pattern=pattern, other_question_patterns=others)
        if qhat is not None:
            abstain = abstains(extraction.class_scores(), extraction.answer.value, qhat)
        else:
            abstain = extraction.answer is Answer.UNKNOWN
        effective = Answer.UNKNOWN if abstain else extraction.answer
        call_answers[claim] = effective
        claims.append(
            {
                "claim": claim,
                "answer": effective.value,
                "stated_answer": extraction.answer.value,
                "trust_score": round(extraction.score, 3),
                "hedged": extraction.hedged,
                "calibrated": qhat is not None,
                "abstain": abstain,
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
                # A row where neither side knows anything is not evidence
                # of anything; keep the waterfall to informative fields.
                if c.call_answer != "unknown" or c.directory_claim != "unknown"
            ],
        },
    }
