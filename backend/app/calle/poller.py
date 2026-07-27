"""Asyncio poller. The webhook's backup, and the loop's heartbeat.

On startup it resumes every submitted run straight from SQLite, so killing
the process mid-call and restarting picks up exactly where it left off.
"""

import asyncio
import json
import logging
from pathlib import Path

from app import db, fsm, runs
from app.calle.client import CalleService

logger = logging.getLogger(__name__)

# A run that cannot be polled this many times in a row is failed, not pending.
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

    def wake(self) -> None:
        """Request an immediate tick and reset backoff.

        Called after a new submission: without this, a run created during an
        idle stretch waits out the full grown backoff (up to 60s) before its
        first poll."""
        self._wake.set()

    async def tick(self) -> int:
        """Poll every submitted run once. Returns how many reached terminal."""
        conn = db.connect(self._database)
        try:
            pending = db.pollable_runs(conn)
        finally:
            conn.close()

        advanced = 0
        for row in pending:
            calle_call_id = str(row["calle_call_id"])
            run_id = str(row["run_id"])
            try:
                call = await self._service.get_call(calle_call_id)
            except Exception as exc:
                # Retrying forever leaves the run "in progress" in the console
                # with a spinner nobody can interpret. Give up loudly instead.
                self._failures[run_id] = self._failures.get(run_id, 0) + 1
                attempts = self._failures[run_id]
                logger.warning(
                    "poll failed for %s (attempt %d of %d)",
                    calle_call_id,
                    attempts,
                    _MAX_POLL_FAILURES,
                    exc_info=True,
                )
                if attempts >= _MAX_POLL_FAILURES:
                    logger.error("giving up on %s after %d poll failures", run_id, attempts)
                    conn = db.connect(self._database)
                    try:
                        fsm.advance(
                            conn,
                            run_id,
                            "failed",
                            terminal_payload=json.dumps(
                                {
                                    "error": f"the call status could not be read after "
                                    f"{attempts} attempts: {exc}",
                                    "stage": "poll_exhausted",
                                }
                            ),
                        )
                    finally:
                        conn.close()
                    self._failures.pop(run_id, None)
                continue
            self._failures.pop(run_id, None)
            if runs.apply_terminal_payload(self._database, call):
                advanced += 1
        return advanced

    async def run_forever(self, stop: asyncio.Event) -> None:
        delay = self._interval
        while not stop.is_set():
            try:
                advanced = await self.tick()
            except Exception:
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
