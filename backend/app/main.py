"""Attest backend API.

The CALL-E integration seam lives in backend/app/calle/. A reviewer should be
able to find the load-bearing CALL-E call within one minute of opening this repo.
"""

import asyncio
import hmac
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import analysis, db, runs
from app.calle.client import CalleService
from app.calle.poller import Poller
from app.calle.webhook import router as webhook_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    service = CalleService()
    stop = asyncio.Event()
    poller = Poller(service, db.db_path())
    task = asyncio.create_task(poller.run_forever(stop))
    task.add_done_callback(
        lambda t: (
            logging.getLogger(__name__).critical(
                "poller task ended unexpectedly: %s",
                t.exception() if not t.cancelled() else "cancelled",
            )
            if not stop.is_set()
            else None
        )
    )
    application.state.calle_service = service
    application.state.poller = poller
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

# Public read-only API for the console; writes stay key-gated. No secrets or
# unmasked phone numbers ever leave the server, so a permissive read origin
# policy is acceptable here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Attest-Key"],
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "attest"}


@app.get("/api/runs")
async def api_runs() -> dict[str, list[dict[str, object]]]:
    conn = db.connect(db.db_path())
    try:
        rows = db.list_runs(conn)
    finally:
        conn.close()
    out: list[dict[str, object]] = []
    for row in rows:
        record = json.loads(str(row["record_json"])) if row["record_json"] else {}
        out.append(
            {
                "run_id": row["run_id"],
                "state": row["state"],
                "created_at": row["created_at"],
                "org": record.get("org"),
                "replay": bool(record.get("replay", False)),
            }
        )
    return {"runs": out}


_AUDIO_TYPES = {".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav"}


def _audio_file(run_id: str) -> Path | None:
    """The locally stored audio for a run, if any.

    The CALL-E API exposes no recording URL (verified 2026-07-26), so any
    audio here was captured on our own end of a consented call and dropped
    into ATTEST_AUDIO_DIR by an operator. Local files only: this never
    fetches anything remote.
    """
    audio_dir = Path(os.environ.get("ATTEST_AUDIO_DIR", "data/audio"))
    for suffix in _AUDIO_TYPES:
        candidate = audio_dir / f"{run_id}{suffix}"
        if candidate.is_file():
            return candidate
    return None


@app.get("/api/runs/{run_id}/audio")
async def api_run_audio(run_id: str) -> FileResponse:
    conn = db.connect(db.db_path())
    try:
        row = db.get_run(conn, run_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    audio = _audio_file(run_id)
    if audio is None:
        raise HTTPException(status_code=404, detail="no audio for this run")
    return FileResponse(audio, media_type=_AUDIO_TYPES[audio.suffix])


@app.get("/api/runs/{run_id}")
async def api_run_detail(run_id: str) -> dict[str, object]:
    conn = db.connect(db.db_path())
    try:
        row = db.get_run(conn, run_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    payload = json.loads(str(row["terminal_payload"])) if row["terminal_payload"] else None
    record = json.loads(str(row["record_json"])) if row["record_json"] else {}
    detail: dict[str, object] = {
        "run_id": row["run_id"],
        "state": row["state"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "payload": analysis.redact_payload(payload) if payload else None,
        "has_audio": _audio_file(run_id) is not None,
    }
    if record.get("audio_note"):
        detail["audio_note"] = str(record["audio_note"])[:160]
    if payload and row["state"] == "completed":
        # Only completed calls get claims and a verdict; a failed run must
        # never dress up as an analysis result.
        detail["analysis"] = analysis.analyze_run(row)
    elif payload and row["state"] in {"failed", "canceled"}:
        detail["failure"] = {
            "error": str(payload.get("error", "unknown failure"))[:200],
            "stage": str(payload.get("stage", "unknown"))[:60],
        }
    return detail


@app.get("/api/metrics")
async def api_metrics() -> dict[str, object]:
    metrics_path = Path(os.environ.get("ATTEST_METRICS_PATH", "eval/results/metrics.json"))
    if not metrics_path.exists():
        raise HTTPException(status_code=404, detail="metrics not generated")
    data: dict[str, object] = json.loads(metrics_path.read_text())
    return data


class StartRunRequest(BaseModel):
    phone: str = Field(pattern=r"^\+1\d{10}$")
    org: str = Field(min_length=2, max_length=120)
    claims: dict[str, str] = Field(default_factory=dict)


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
    record: dict[str, object] = {"org": body.org, "claims": body.claims}
    # The disclosure-first task is built server-side: no client can submit a
    # call script with the disclosure removed.
    task = runs.build_task(body.org, body.claims)
    async with _submission_lock:
        run_id = await runs.start_verification_run(
            _get_service(), db.db_path(), task=task, phone=body.phone, record=record
        )
    # Fresh submissions poll immediately instead of waiting out idle backoff.
    poller = getattr(app.state, "poller", None)
    if poller is not None:
        poller.wake()
    return {"run_id": run_id}
