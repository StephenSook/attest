"""Server-side analysis of terminal payloads for the console.

The browser never computes or submits verdicts: extraction and reconciliation
run here, on the server-stored payload, and the API serves the result.
Phone numbers are redacted before anything leaves the server.
"""

import copy
import ipaddress
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, cast

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

_PHONE_CANDIDATE = re.compile(
    r"(?<!\w)\+?(?:\d[\s()./-]*){6,14}\d(?:\s*(?:(?:ext\.?|x)\s*\d{1,6}))?(?!\w)",
    re.IGNORECASE,
)
_DATE_LIKE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2})?")
_SLASH_DATE_LIKE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")


def _mask(phone: str) -> str:
    if len(phone) < 7:
        return "***"
    return phone[:3] + "*" * (len(phone) - 6) + phone[-3:]


def _mask_phone_text(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        candidate = match.group(0)
        stripped = candidate.strip()
        if _DATE_LIKE.fullmatch(stripped) or _SLASH_DATE_LIKE.fullmatch(stripped):
            return candidate
        try:
            ipaddress.ip_address(stripped)
        except ValueError:
            return "[redacted phone]"
        return candidate

    return _PHONE_CANDIDATE.sub(replace, text)


def _redact_phone_fields(value: Any, *, context: str = "generic") -> Any:
    """Redact phone data using the payload field's semantic context."""
    if isinstance(value, dict):
        container_contexts = {
            "recipients": ("recipient", "recipient"),
            "attempts": ("attempt", "attempt"),
            "turns": ("turn", "turn"),
        }
        if context in container_contexts:
            child_context, key_prefix = container_contexts[context]
            items = list(value.values())
            value.clear()
            for index, nested in enumerate(items):
                value[f"{key_prefix}-{index}"] = _redact_phone_fields(nested, context=child_context)
            return value

        items = list(value.items())
        for key, nested in items:
            key_lower = str(key).lower()
            child_context = {
                "phone": "phone",
                "phones": "phone",
                "recipients": "recipients",
                "attempts": "attempts",
                "transcript_turns": "turns",
            }.get(key_lower, "generic")
            if context == "turn" and key_lower == "text":
                child_context = "transcript_text"
            value[key] = _redact_phone_fields(nested, context=child_context)
        return value
    if isinstance(value, list):
        child_context = {
            "recipients": "recipient",
            "attempts": "attempt",
            "turns": "turn",
        }.get(context, context)
        return [_redact_phone_fields(item, context=child_context) for item in value]
    if context in {"phone", "recipient"} and value is not None:
        return _mask(str(value))
    if context in {"attempt", "turn", "transcript_text"} and isinstance(value, str):
        return _mask_phone_text(value)
    return value


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Mask phone numbers and remove request echoes before storage or serving."""
    redacted = copy.deepcopy(payload)
    # The mock create path stores the original request, which carries the raw
    # dialed number under request.recipient; strip the whole echo rather than
    # chase its shape.
    redacted.pop("request", None)
    _redact_phone_fields(redacted)
    return redacted


def _container_items(value: Any) -> list[Any]:
    """Return members from either a JSON list or an id-keyed JSON object."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def transcript_turns(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Find the transcript in a terminal payload.

    `or []` rather than a default, because the API sends an explicit null for
    a list it has no value for, and a default only covers the absent key. The
    served path raised TypeError on a payload carrying "recipients": null.
    """
    for recipient in _container_items(payload.get("recipients")):
        if not isinstance(recipient, dict):
            continue
        for attempt in _container_items(recipient.get("attempts")):
            if not isinstance(attempt, dict):
                continue
            turns = attempt.get("transcript_turns")
            if isinstance(turns, list) and turns:
                valid_turns = [
                    cast(dict[str, Any], turn) for turn in turns if isinstance(turn, dict)
                ]
                if valid_turns:
                    return valid_turns
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
