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
from datetime import date, datetime
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
_IDENTIFIER_PHONE_CANDIDATE = re.compile(
    r"\+?(?:\d[\s()./-]*){6,14}\d(?:\s*(?:(?:ext\.?|x)\s*\d{1,6}))?",
    re.IGNORECASE,
)
_DATE_LIKE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2})?")
_SLASH_DATE_LIKE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
_ISO_DATE_TIME = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_PROVIDER_CALL_ID = re.compile(r"call_[A-Za-z0-9_-]{22}")
_PROVIDER_CHILD_ID = re.compile(r"(?:rcp|att)_[0-9a-fA-F]{16}")
_PROVIDER_TRANSPORT_ID = re.compile(r"[0-9a-fA-F]{32}")
_UUID_ID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_KNOWN_ID_PREFIXES = frozenset(
    {"call", "recipient", "attempt", "turn", "provider", "event", "task", "transcript"}
)


def _mask(phone: str) -> str:
    if len(phone) < 7:
        return "***"
    return phone[:3] + "*" * (len(phone) - 6) + phone[-3:]


def _mask_phone_text(text: str) -> str:
    return _PHONE_CANDIDATE.sub("[redacted phone]", text)


def _is_safe_provider_id(text: str) -> bool:
    return bool(_PROVIDER_CALL_ID.fullmatch(text) or _PROVIDER_CHILD_ID.fullmatch(text))


def _mask_identifier_text(text: str) -> str:
    if _UUID_ID.fullmatch(text) or _is_safe_provider_id(text):
        return text
    return _IDENTIFIER_PHONE_CANDIDATE.sub("[redacted phone]", text)


def _mask_generic_mapping_key(text: str) -> str:
    if _is_valid_date_text(text):
        return text
    return _mask_identifier_text(text)


def _is_valid_date_text(text: str) -> bool:
    try:
        if _SLASH_DATE_LIKE.fullmatch(text):
            for date_format in ("%m/%d/%Y", "%m/%d/%y"):
                try:
                    datetime.strptime(text, date_format)
                except ValueError:
                    continue
                return True
            return False
        if _ISO_DATE_TIME.fullmatch(text):
            datetime.fromisoformat(text.replace("Z", "+00:00"))
            return True
        if _DATE_LIKE.fullmatch(text):
            date.fromisoformat(text)
            return True
    except ValueError:
        return False
    return False


def _normalized_key(key: object) -> str:
    key_text = str(key)
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key_text)
    return re.sub(r"[.\-\s]+", "_", snake).lower()


def _is_identifier_key(key: object) -> bool:
    normalized = _normalized_key(key)
    tokens = normalized.split("_")
    if any(token in {"id", "ids"} for token in tokens):
        return True
    compact = normalized.replace("_", "")
    return any(compact in {f"{prefix}id", f"{prefix}ids"} for prefix in _KNOWN_ID_PREFIXES)


def _is_date_key(key: object) -> bool:
    normalized = _normalized_key(key)
    return normalized in {"date", "time", "timestamp"} or normalized.endswith(
        ("_at", "_date", "_time", "_timestamp")
    )


def _is_ip_key(key: object) -> bool:
    return "ip" in _normalized_key(key).split("_")


def _is_phone_key(key: object) -> bool:
    return bool({"phone", "telephone", "mobile"} & set(_normalized_key(key).split("_")))


def _redact_phone_fields(value: Any, *, context: str = "generic") -> Any:
    """Redact phone data using the payload field's semantic context."""
    if isinstance(value, dict):
        mask_key = _mask_generic_mapping_key if context == "generic" else _mask_identifier_text
        container_contexts = {
            "recipients": ("recipient", "recipient"),
            "attempts": ("attempt", "attempt"),
            "turns": ("turn", "turn"),
        }
        if context in container_contexts:
            child_context, key_prefix = container_contexts[context]
            items = list(value.items())
            safe_keys = {str(key) for key, _ in items if mask_key(str(key)) == str(key)}
            used_keys = set(safe_keys)
            next_placeholder = 0
            value.clear()
            for key, nested in items:
                key_text = str(key)
                if mask_key(key_text) != key_text:
                    replacement = f"{key_prefix}-{next_placeholder}"
                    while replacement in used_keys:
                        next_placeholder += 1
                        replacement = f"{key_prefix}-{next_placeholder}"
                    output_key: object = replacement
                    used_keys.add(replacement)
                    next_placeholder += 1
                else:
                    output_key = key
                value[output_key] = _redact_phone_fields(nested, context=child_context)
            return value

        items = list(value.items())
        sensitive_mapping_contexts = {
            "phone": "phone",
            "recipient": "recipient-field",
            "attempt": "attempt-field",
            "turn": "turn-field",
            "transcript_text": "text-field",
            "identifier": "identifier-field",
        }
        sensitive_key_prefix = sensitive_mapping_contexts.get(context, "field")
        safe_keys = {str(key) for key, _ in items if mask_key(str(key)) == str(key)}
        used_keys = set(safe_keys)
        sanitized_items: list[tuple[object, Any]] = []
        next_placeholder = 0
        for key, nested in items:
            key_text = str(key)
            if mask_key(key_text) != key_text:
                replacement = f"{sensitive_key_prefix}-{next_placeholder}"
                while replacement in used_keys:
                    next_placeholder += 1
                    replacement = f"{sensitive_key_prefix}-{next_placeholder}"
                sanitized_key: object = replacement
                used_keys.add(replacement)
                next_placeholder += 1
            else:
                sanitized_key = key
            sanitized_items.append((sanitized_key, nested))
        items = sanitized_items
        value.clear()
        for key, nested in items:
            key_lower = str(key).lower()
            nested_context: str | None = {
                "phone": "phone",
                "phones": "phone",
                "recipients": "recipients",
                "attempts": "attempts",
                "transcript_turns": "turns",
                "summary": "transcript_text",
                "failure_message": "transcript_text",
                "error": "transcript_text",
            }.get(key_lower)
            normalized_key = _normalized_key(key)
            is_identifier_key = _is_identifier_key(key)
            if _is_phone_key(key):
                nested_context = "phone"
            elif normalized_key == "provider_call_id":
                nested_context = "provider_identifier"
            elif is_identifier_key:
                nested_context = "identifier"
            elif _is_date_key(key):
                nested_context = "date_value"
            elif _is_ip_key(key):
                nested_context = "ip_value"
            elif nested_context is None:
                nested_context = (
                    context
                    if context
                    in {
                        "phone",
                        "recipient",
                        "attempt",
                        "turn",
                        "transcript_text",
                        "identifier",
                        "provider_identifier",
                    }
                    else "generic"
                )
            if context == "turn" and key_lower == "text":
                nested_context = "transcript_text"
            value[key] = _redact_phone_fields(nested, context=nested_context)
        return value
    if isinstance(value, list):
        if context == "recipients":
            return [
                _redact_phone_fields(
                    item,
                    context="recipient" if isinstance(item, dict) else "recipients",
                )
                for item in value
            ]
        child_context = {
            "attempts": "attempt",
            "turns": "turn",
        }.get(context, context)
        return [_redact_phone_fields(item, context=child_context) for item in value]
    if context == "phone" and value is not None:
        return _mask(str(value))
    if context == "recipients" and value is not None:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and _is_safe_provider_id(value):
            return value
        return _mask(str(value))
    if context == "date_value":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and _is_valid_date_text(value):
            return value
    if context == "ip_value" and isinstance(value, str):
        try:
            ipaddress.ip_address(value.strip())
        except ValueError:
            pass
        else:
            return value
    if (
        context == "provider_identifier"
        and isinstance(value, str)
        and _PROVIDER_TRANSPORT_ID.fullmatch(value)
    ):
        return value
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value)
        redacted = (
            _mask_identifier_text(text)
            if context in {"identifier", "provider_identifier"}
            else _mask_phone_text(text)
        )
        return redacted if redacted != text else value
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


def redact_payload_json(payload_json: str) -> str:
    """Apply the same no-raw-phone boundary to every persisted JSON payload."""
    parsed = json.loads(payload_json)
    redacted = copy.deepcopy(parsed)
    if isinstance(redacted, dict):
        redacted.pop("request", None)
    _redact_phone_fields(redacted)
    return json.dumps(redacted)


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
    raw_payload = json.loads(str(row["terminal_payload"])) if row["terminal_payload"] else {}
    payload = redact_payload(raw_payload)
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
