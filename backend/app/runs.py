"""Run lifecycle: create a verification run and hand it to CALL-E."""

import json
import logging
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any, cast

from calle.errors import CalleAPIError, CalleConnectionError, CalleTimeoutError

from app import analysis, db, fsm
from app.calle.client import CalleService

logger = logging.getLogger(__name__)

_DEFINITE_REJECTION_STATUS_CODES = frozenset({400, 401, 403, 404, 422, 429})
DISPATCH_LEASE_SECONDS = 120.0
DISPATCH_RECOVERY_WINDOW_SECONDS = 600.0


class CallSubmissionRejected(Exception):
    """CALL-E definitively rejected a request before accepting a call."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"CALL-E rejected the call request ({status_code})")
        self.status_code = status_code


class CallSubmissionBusy(Exception):
    """Another process still owns the external submission attempt."""


class CallSubmissionExpired(Exception):
    """The safe retry window ended, so Attest refused to dial late."""


def _record_ambiguous_submit(
    conn: sqlite3.Connection,
    run_id: str,
    exc: Exception,
) -> None:
    """Keep a possibly accepted submission retryable under the same key."""
    recorded = db.set_submit_error(
        conn,
        run_id,
        json.dumps({"error": str(exc), "stage": "submit_ambiguous"}),
    )
    if recorded:
        logger.warning("ambiguous submit for %s: safe retry available", run_id)
    else:
        logger.info("late ambiguous submit for %s ignored after acceptance", run_id)


def _stored_definite_rejection_status(row: sqlite3.Row) -> int | None:
    """Return the provider status for a previously completed rejection."""
    if row["state"] != "failed" or row["calle_call_id"]:
        return None
    try:
        payload = json.loads(str(row["terminal_payload"] or ""))
    except json.JSONDecodeError:
        return None
    if payload.get("classification") != "definite_rejection":
        return None
    status_code = payload.get("provider_status_code")
    return status_code if isinstance(status_code, int) else None


def _stored_failure_stage(row: sqlite3.Row) -> str | None:
    if row["state"] != "failed" or row["calle_call_id"]:
        return None
    try:
        payload = json.loads(str(row["terminal_payload"] or ""))
    except json.JSONDecodeError:
        return None
    stage = payload.get("stage")
    return stage if isinstance(stage, str) else None


# How the agent must behave once the questions are asked. Held as one constant
# because the shipped skill carries its own copy of the task builder and cannot
# import this module: skills/verify-by-phone is standard-library-only by design
# so it installs on machines that never see this repository. The two copies had
# already drifted (the skill was missing the voicemail rule entirely), which is
# the same sync-by-comment failure that let the extractor and the abstention
# gate diverge. tests/test_skill_parity.py pins them to the same string.
CALL_CONDUCT = (
    "First establish that you have reached the organization named above. If the "
    "person says you have reached a different business, a private residence, or a "
    "wrong number, do NOT ask the verification questions: thank them and end the "
    "call, because an answer from somewhere else is not evidence about this "
    "listing. "
    "Record the answers exactly as given. If the person "
    "hedges, capture their exact wording. If they decline to speak with an automated "
    "caller, thank them and end the call immediately. If asked to hold, wait briefly, "
    "then thank them and end the call rather than waiting indefinitely. If you "
    "reach voicemail or an answering machine, do NOT leave a message: end the "
    "call politely and immediately, because a directory answer cannot be "
    "established from a recording and nobody should find a robot message on "
    "their line. If you are asked for patient details, such as a name, a date of "
    "birth, an insurance member or card number, or a reason for the visit, say "
    "plainly that you do not have that information because this is a directory "
    "verification call and not an appointment request, then repeat the question "
    "you called to ask. Never invent any such detail, not even a placeholder. "
    "Never guess: "
    "anything not clearly stated must be recorded as unknown. Keep the call under two "
    "minutes and always remain polite."
)


def build_task(org: str, claims: dict[str, str]) -> str:
    """The disclosure-first call script. Server-owned: disclosure is not
    something a client is allowed to omit."""
    questions = [
        f"first, confirm you have reached {org} by asking: 'Is this the office of {org}?'",
        "then ask whether the practice is currently accepting new patients",
    ]
    plan = claims.get("plan_name")
    if plan:
        questions.append(f"then ask whether the practice currently accepts {plan}")
    asks = "; ".join(questions)
    return (
        f"You are placing a short verification call to {org} on behalf of a records "
        "verification service. Open with: 'Hi, this is an automated assistant calling "
        f"to verify directory information for {org}. This call may be recorded.' "
        f"Then ask ONE question at a time, waiting for an answer before asking "
        f"the next: {asks}. " + CALL_CONDUCT
    )


def _dispatch_request(
    service: CalleService,
    task: str,
    phone: str,
) -> tuple[str | None, str, dict[str, object]]:
    """Key the exact request and transport identity without storing the phone."""
    public_base = os.environ.get("ATTEST_PUBLIC_BASE_URL", "").rstrip("/")
    webhook_url = f"{public_base}/calle/webhook" if public_base else None
    transport = service.dispatch_identity()
    request = {
        "phone": phone,
        "task": task,
        "transport": transport,
        "webhook_url": webhook_url,
    }
    canonical = json.dumps(request, separators=(",", ":"), sort_keys=True)
    return webhook_url, service.dispatch_digest(canonical), transport


async def start_verification_run(
    service: CalleService,
    database: Path,
    *,
    task: str,
    phone: str,
    record: dict[str, object] | None = None,
    run_id: str | None = None,
    connection: sqlite3.Connection | None = None,
    sandbox_phone_hash: str | None = None,
    destination_hash: str = "",
) -> str:
    """Create or resume a run, submit the call to CALL-E, and record it.

    The run id doubles as CALL-E's idempotency key. A client-supplied stable
    run id therefore makes a lost create response safely retryable without a
    second dial. `record` carries the claims stored for reconciliation.
    """
    resolved_run_id = run_id or f"run_{uuid.uuid4().hex[:16]}"
    dispatch_webhook_url, dispatch_digest, transport = _dispatch_request(service, task, phone)
    dispatch_base_url = str(transport.get("base_url", ""))
    dispatch_provider = str(transport.get("provider", ""))
    credential_fingerprint = str(transport.get("credential_fingerprint", ""))
    if not dispatch_base_url or not dispatch_provider or not credential_fingerprint:
        raise RuntimeError("CALL-E service did not expose a complete transport identity")
    if not destination_hash:
        destination_hash = service.dispatch_digest(f"destination:{phone}")
    lease_owner = uuid.uuid4().hex
    owns_connection = connection is None
    conn = connection or db.connect(database)
    try:
        row = db.get_run(conn, resolved_run_id)
        if row is None:
            db.create_run(
                conn,
                run_id=resolved_run_id,
                idempotency_key=resolved_run_id,
                record_json=json.dumps(record) if record else None,
            )
            row = db.get_run(conn, resolved_run_id)
        if row is not None and row["calle_call_id"]:
            if row["state"] == "created":
                db.accept_submission(conn, resolved_run_id, str(row["calle_call_id"]))
            return resolved_run_id
        if row is not None:
            stored_rejection = _stored_definite_rejection_status(row)
            if stored_rejection is not None:
                raise CallSubmissionRejected(stored_rejection)
            if _stored_failure_stage(row) == "submit_recovery_expired":
                raise CallSubmissionExpired
        if row is not None and row["state"] != "created":
            raise RuntimeError(f"run {resolved_run_id} is not retryable")
        claim, attempt_number = db.claim_submission_attempt(
            conn,
            resolved_run_id,
            dispatch_digest=dispatch_digest,
            dispatch_base_url=dispatch_base_url,
            dispatch_provider=dispatch_provider,
            dispatch_credential_fingerprint=credential_fingerprint,
            destination_hash=destination_hash,
            lease_owner=lease_owner,
            lease_seconds=DISPATCH_LEASE_SECONDS,
            recovery_window_seconds=DISPATCH_RECOVERY_WINDOW_SECONDS,
        )
        if claim == "busy":
            raise CallSubmissionBusy
        if claim == "expired":
            raise CallSubmissionExpired
        if claim == "mismatch":
            raise RuntimeError(f"run {resolved_run_id} cannot change its destination or provider")
        if claim == "closed":
            closed = db.get_run(conn, resolved_run_id)
            if closed is not None and closed["calle_call_id"]:
                return resolved_run_id
            if closed is not None:
                stored_rejection = _stored_definite_rejection_status(closed)
                if stored_rejection is not None:
                    raise CallSubmissionRejected(stored_rejection)
                if _stored_failure_stage(closed) == "submit_recovery_expired":
                    raise CallSubmissionExpired
            raise RuntimeError(f"run {resolved_run_id} closed during submission")
        if claim != "claimed":
            raise RuntimeError(f"unknown submission claim outcome {claim}")
        try:
            created = await service.place_call(
                task=task,
                phone=phone,
                idempotency_key=resolved_run_id,
                webhook_url=dispatch_webhook_url,
            )
        except (CalleTimeoutError, CalleConnectionError, json.JSONDecodeError) as exc:
            # Ambiguous: CALL-E may have ACCEPTED the call even though our
            # request died, so a real phone may still ring. The run_id is the
            # Idempotency-Key, so a future resubmission with this run_id can
            # never double-dial. Recorded distinctly for reconciliation.
            _record_ambiguous_submit(conn, resolved_run_id, exc)
            db.release_submission_lease(conn, resolved_run_id, lease_owner)
            raise
        except CalleAPIError as exc:
            if exc.status_code not in _DEFINITE_REJECTION_STATUS_CODES or attempt_number > 1:
                # A server error does not prove the provider rejected the
                # request. A later 4xx also cannot erase an earlier attempt
                # that may already have been accepted before its response was
                # lost. The original reservation therefore remains consumed.
                _record_ambiguous_submit(conn, resolved_run_id, exc)
                db.release_submission_lease(conn, resolved_run_id, lease_owner)
                raise
            rejected = db.reject_submission(
                conn,
                resolved_run_id,
                json.dumps(
                    {
                        "classification": "definite_rejection",
                        "error": str(exc),
                        "provider_status_code": exc.status_code,
                        "stage": "submit",
                    }
                ),
                lease_owner=lease_owner,
                attempt_number=attempt_number,
                sandbox_phone_hash=sandbox_phone_hash,
            )
            if not rejected:
                logger.warning(
                    "stale definite rejection ignored for %s attempt %d",
                    resolved_run_id,
                    attempt_number,
                )
                raise
            raise CallSubmissionRejected(exc.status_code) from exc
        except Exception as exc:
            # An unclassified SDK or transport error does not prove whether
            # the provider accepted the request. Preserve the stable key.
            _record_ambiguous_submit(conn, resolved_run_id, exc)
            db.release_submission_lease(conn, resolved_run_id, lease_owner)
            raise
        calle_call_id = str(created.get("id") or "")
        if not calle_call_id:
            # The provider may have accepted the call before returning a
            # malformed response. Keep the stable idempotency key retryable.
            db.set_submit_error(
                conn,
                resolved_run_id,
                json.dumps({"error": "provider returned no call id", "stage": "submit_no_id"}),
            )
            db.release_submission_lease(conn, resolved_run_id, lease_owner)
            raise RuntimeError("CALL-E returned no call id")
        db.accept_submission(conn, resolved_run_id, calle_call_id)
        return resolved_run_id
    finally:
        if owns_connection:
            conn.close()


def apply_terminal_payload(database: Path, payload: dict[str, object]) -> bool:
    """Idempotently record a terminal CALL-E payload against its run.

    Used by both the poller and the webhook receiver; whichever lands first
    wins and the second call is a no-op. Returns True if this call landed.
    """
    status = str(payload.get("status", ""))
    if status not in fsm.TERMINAL_STATES:
        if status not in {"queued", "dialing", "in_progress", "ringing"}:
            # A terminal-but-unknown status would strand the run in submitted
            # forever with no evidence. Be loud about vocabulary we have
            # never seen.
            logger.warning("unknown CALL-E status %r for call %s", status, payload.get("id"))
        return False
    calle_call_id = str(payload.get("id", ""))
    conn = db.connect(database)
    try:
        row = db.get_run_by_calle_call_id(conn, calle_call_id)
        if row is None:
            logger.warning("terminal payload for unknown call id %s dropped", calle_call_id)
            return False
        if row["state"] == "created":
            db.accept_submission(conn, str(row["run_id"]), calle_call_id)
        stored_payload = analysis.redact_payload(cast(dict[str, Any], payload))
        return fsm.advance(
            conn,
            str(row["run_id"]),
            status,
            terminal_payload=json.dumps(stored_payload),
        )
    finally:
        conn.close()
