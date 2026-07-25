"""Run lifecycle: create a verification run and hand it to CALL-E."""

import json
import logging
import uuid
from pathlib import Path

from calle.errors import CalleConnectionError, CalleTimeoutError

from app import db, fsm
from app.calle.client import CalleService

logger = logging.getLogger(__name__)


async def start_verification_run(
    service: CalleService,
    database: Path,
    *,
    task: str,
    phone: str,
) -> str:
    """Create a run row, submit the call to CALL-E, record the outcome.

    The run_id doubles as the Idempotency-Key, so re-submitting the same run
    can never create a second call.
    """
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    conn = db.connect(database)
    try:
        db.create_run(conn, run_id=run_id, idempotency_key=run_id)
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
        db.set_calle_call_id(conn, run_id, str(created.get("id", "")))
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
        return False
    calle_call_id = str(payload.get("id", ""))
    conn = db.connect(database)
    try:
        row = db.get_run_by_calle_call_id(conn, calle_call_id)
        if row is None:
            return False
        return fsm.advance(
            conn,
            str(row["run_id"]),
            status,
            terminal_payload=json.dumps(payload),
        )
    finally:
        conn.close()
