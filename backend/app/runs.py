"""Run lifecycle: create a verification run and hand it to CALL-E."""

import json
import logging
import uuid
from pathlib import Path

from calle.errors import CalleConnectionError, CalleTimeoutError

from app import db, fsm
from app.calle.client import CalleService

logger = logging.getLogger(__name__)


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
        f"Then politely ask: {asks}. " + CALL_CONDUCT
    )


async def start_verification_run(
    service: CalleService,
    database: Path,
    *,
    task: str,
    phone: str,
    record: dict[str, object] | None = None,
) -> str:
    """Create a run row, submit the call to CALL-E, record the outcome.

    The run_id doubles as the Idempotency-Key, so re-submitting the same run
    can never create a second call. `record` carries the directory claims the
    call verifies, stored server-side for reconciliation.
    """
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    conn = db.connect(database)
    try:
        db.create_run(
            conn,
            run_id=run_id,
            idempotency_key=run_id,
            record_json=json.dumps(record) if record else None,
        )
        try:
            created = await service.place_call(task=task, phone=phone, idempotency_key=run_id)
        except (CalleTimeoutError, CalleConnectionError) as exc:
            # Ambiguous: CALL-E may have ACCEPTED the call even though our
            # request died, so a real phone may still ring. The run_id is the
            # Idempotency-Key, so a future resubmission with this run_id can
            # never double-dial. Recorded distinctly for reconciliation.
            logger.warning("ambiguous submit for %s: possible orphaned call", run_id)
            fsm.advance(
                conn,
                run_id,
                "failed",
                terminal_payload=json.dumps({"error": str(exc), "stage": "submit_ambiguous"}),
            )
            raise
        except Exception as exc:
            fsm.advance(
                conn,
                run_id,
                "failed",
                terminal_payload=json.dumps({"error": str(exc), "stage": "submit"}),
            )
            raise
        calle_call_id = str(created.get("id") or "")
        if not calle_call_id:
            # Advancing to submitted with an empty id would create a zombie
            # the poller retries forever. Fail loudly instead.
            fsm.advance(
                conn,
                run_id,
                "failed",
                terminal_payload=json.dumps(
                    {"error": "provider returned no call id", "stage": "submit_no_id"}
                ),
            )
            raise RuntimeError("CALL-E returned no call id")
        db.set_calle_call_id(conn, run_id, calle_call_id)
        fsm.advance(conn, run_id, "submitted")
        return run_id
    finally:
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
        return fsm.advance(
            conn,
            str(row["run_id"]),
            status,
            terminal_payload=json.dumps(payload),
        )
    finally:
        conn.close()
