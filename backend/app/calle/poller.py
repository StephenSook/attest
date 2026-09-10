"""Asyncio poller. The webhook's backup, and the loop's heartbeat."""

import asyncio
import json
import logging
import time
from pathlib import Path

from app import db, runs
from app.calle.client import CalleService

logger = logging.getLogger(__name__)

# After this many failures, expose the recovery block while continuing to poll.
_MAX_POLL_FAILURES = 5


class Poller:
    def __init__(
        self,
        service: CalleService,
        database: Path,
        *,
        interval_seconds: float = 5.0,
        max_interval_seconds: float = 60.0,
    ) -> None:
        self._service = service
        self._database = database
        self._interval = interval_seconds
        self._max_interval = max_interval_seconds
        self._wake = asyncio.Event()
        self._failures: dict[str, int] = {}
        self._transport_mismatches: set[str] = set()
        self._last_successful_tick: float | None = None
        self._last_error: str | None = None

    @property
    def healthy(self) -> bool:
        """True only after a recent tick completed every recoverable path."""
        if self._last_successful_tick is None or self._last_error is not None:
            return False
        stale_after = max(self._max_interval * 2, self._interval * 3, 10.0)
        return time.monotonic() - self._last_successful_tick <= stale_after

    @property
    def blocked_run_count(self) -> int:
        exhausted = {
            run_id for run_id, attempts in self._failures.items() if attempts >= _MAX_POLL_FAILURES
        }
        conn = db.connect(self._database)
        try:
            persisted = db.recovery_blocked_run_ids(conn)
        finally:
            conn.close()
        return len(self._transport_mismatches | exhausted | persisted)

    def wake(self) -> None:
        """Request an immediate tick and reset backoff.

        Called after a new submission: without this, a run created during an
        idle stretch waits out the full grown backoff (up to 60s) before its
        first poll."""
        self._wake.set()

    async def tick(self) -> int:
        """Expire abandoned submissions, then poll accepted runs once."""
        conn = db.connect(self._database)
        try:
            expired = db.expire_submission_attempts(conn)
        finally:
            conn.close()

        if expired:
            logger.error("expired %d unreconciled CALL-E dispatches", expired)

        conn = db.connect(self._database)
        try:
            pending = db.pollable_runs(conn)
        finally:
            conn.close()

        pending_ids = {str(row["run_id"]) for row in pending}
        self._transport_mismatches.intersection_update(pending_ids)
        self._failures = {
            run_id: failures for run_id, failures in self._failures.items() if run_id in pending_ids
        }
        advanced = 0
        tick_failed = False
        for row in pending:
            calle_call_id = str(row["calle_call_id"])
            run_id = str(row["run_id"])
            identity = {
                "base_url": row["dispatch_base_url"],
                "provider": row["dispatch_provider"],
                "credential_fingerprint": row["dispatch_credential_fingerprint"],
            }
            recovery_status = self._service.accepted_call_recovery_status(identity)
            if recovery_status == "transport_changed":
                tick_failed = True
                self._transport_mismatches.add(run_id)
                conn = db.connect(self._database)
                try:
                    db.set_recovery_issue(
                        conn,
                        run_id,
                        json.dumps(
                            {
                                "error": (
                                    "CALL-E endpoint or provider no longer matches the original "
                                    "dispatch. Restore them to resume polling."
                                ),
                                "stage": "transport_identity_mismatch",
                            }
                        ),
                    )
                finally:
                    conn.close()
                logger.error(
                    "poll skipped for %s: CALL-E endpoint or provider changed",
                    run_id,
                )
                continue
            try:
                call = await self._service.get_call(calle_call_id)
                if str(call.get("id") or "") != calle_call_id:
                    raise RuntimeError("CALL-E returned a different call id during recovery")
            except Exception as exc:
                tick_failed = True
                self._failures[run_id] = min(
                    self._failures.get(run_id, 0) + 1,
                    _MAX_POLL_FAILURES,
                )
                attempts = self._failures[run_id]
                logger.warning(
                    "poll failed for %s (attempt %d of %d)",
                    calle_call_id,
                    attempts,
                    _MAX_POLL_FAILURES,
                    exc_info=True,
                )
                if attempts >= _MAX_POLL_FAILURES:
                    logger.error(
                        "call state remains unknown for %s after %d poll failures",
                        run_id,
                        attempts,
                    )
                    conn = db.connect(self._database)
                    try:
                        db.set_recovery_issue(
                            conn,
                            run_id,
                            json.dumps(
                                {
                                    "error": f"the call status could not be read after "
                                    f"{attempts} attempts: {exc}",
                                    "stage": "poll_exhausted",
                                }
                            ),
                        )
                    finally:
                        conn.close()
                continue
            self._failures.pop(run_id, None)
            conn = db.connect(self._database)
            try:
                if recovery_status != "match":
                    current_identity = self._service.dispatch_identity()
                    rebound = db.rebind_accepted_dispatch_identity(
                        conn,
                        run_id,
                        calle_call_id,
                        dispatch_base_url=str(current_identity["base_url"]),
                        dispatch_provider=str(current_identity["provider"]),
                        dispatch_credential_fingerprint=str(
                            current_identity["credential_fingerprint"]
                        ),
                    )
                    if not rebound:
                        tick_failed = True
                        self._transport_mismatches.add(run_id)
                        db.set_recovery_issue(
                            conn,
                            run_id,
                            json.dumps(
                                {
                                    "error": (
                                        "CALL-E authenticated the call read, but its transport "
                                        "identity could not be rebound safely."
                                    ),
                                    "stage": "transport_rebind_failed",
                                }
                            ),
                        )
                        continue
                self._transport_mismatches.discard(run_id)
                db.clear_recovery_issue(conn, run_id, "transport_identity_mismatch")
                db.clear_recovery_issue(conn, run_id, "transport_rebind_failed")
                db.clear_recovery_issue(conn, run_id, "poll_exhausted")
            finally:
                conn.close()
            if runs.apply_terminal_payload(self._database, call):
                advanced += 1
        if tick_failed or self._transport_mismatches or self._failures or self.blocked_run_count:
            self._last_error = "one or more submitted runs could not be recovered"
        else:
            self._last_error = None
            self._last_successful_tick = time.monotonic()
        return advanced

    async def run_forever(self, stop: asyncio.Event) -> None:
        delay = self._interval
        while not stop.is_set():
            try:
                advanced = await self.tick()
            except Exception as exc:
                self._last_error = f"poller tick failed: {type(exc).__name__}"
                logger.exception("poller tick crashed; backing off")
                advanced = 0
            delay = self._interval if advanced else min(delay * 2, self._max_interval)
            if self._wake.is_set():
                self._wake.clear()
                delay = self._interval
            stop_task = asyncio.ensure_future(stop.wait())
            wake_task = asyncio.ensure_future(self._wake.wait())
            done, pending = await asyncio.wait(
                {stop_task, wake_task},
                timeout=delay,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if wake_task in done:
                self._wake.clear()
                delay = self._interval
