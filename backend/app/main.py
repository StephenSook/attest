"""Attest backend API.

The CALL-E integration seam lives in backend/app/calle/. A reviewer should be
able to find the load-bearing CALL-E call within one minute of opening this repo.
"""

import asyncio
import hmac
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app import db, runs
from app.calle.client import CalleService
from app.calle.poller import Poller
from app.calle.webhook import router as webhook_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    service = CalleService()
    stop = asyncio.Event()
    poller = Poller(service, db.db_path())
    task = asyncio.create_task(poller.run_forever(stop))
    application.state.calle_service = service
    try:
        yield
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, timeout=10.0)
        except TimeoutError:
            task.cancel()
        finally:
            service.close()


app = FastAPI(title="Attest", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "attest"}


class StartRunRequest(BaseModel):
    task: str = Field(min_length=1)
    phone: str = Field(pattern=r"^\+1\d{10}$")


def _require_internal_key(provided: str | None) -> None:
    """Fail closed: 503 when the key is unconfigured, 403 on mismatch."""
    expected = os.environ.get("ATTEST_JUDGE_KEY", "")
    if not expected:
        raise HTTPException(status_code=503, detail="run creation unavailable")
    if provided is None or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="forbidden")


def _get_service() -> CalleService:
    service = getattr(app.state, "calle_service", None)
    if service is None:
        service = CalleService()
        app.state.calle_service = service
    return service


# One verification call at a time is a product invariant, not a hope.
_submission_lock = asyncio.Lock()


@app.post("/internal/runs", status_code=201)
async def start_run(
    body: StartRunRequest,
    x_attest_key: str | None = Header(default=None, alias="X-Attest-Key"),
) -> dict[str, str]:
    _require_internal_key(x_attest_key)
    async with _submission_lock:
        run_id = await runs.start_verification_run(
            _get_service(), db.db_path(), task=body.task, phone=body.phone
        )
    return {"run_id": run_id}
