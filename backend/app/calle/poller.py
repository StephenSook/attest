"""Asyncio poller. The webhook's backup, and the loop's heartbeat.

On startup it resumes every submitted run straight from SQLite, so killing
the process mid-call and restarting picks up exactly where it left off.
"""

import asyncio
import logging
from pathlib import Path

from app import db, runs
from app.calle.client import CalleService

logger = logging.getLogger(__name__)


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
            try:
                call = await self._service.get_call(calle_call_id)
            except Exception:
                logger.warning("poll failed for %s; will retry", calle_call_id, exc_info=True)
                continue
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
