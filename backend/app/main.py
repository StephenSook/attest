"""Attest backend API.

The CALL-E integration seam lives in backend/app/calle/. A reviewer should be
able to find the load-bearing CALL-E call within one minute of opening this repo.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
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


def _jcs_numbers(value: object) -> object:
    """Integral floats become ints, recursively, so Python's JSON and a
    JavaScript re-serialization of the parsed document agree byte for byte
    (Python writes 1.0 where JS writes 1). Applied to the document BEFORE
    signing, so what is served is what was signed."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _jcs_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jcs_numbers(v) for v in value]
    return value


def _signing_key() -> Ed25519PrivateKey | None:
    """The Ed25519 signing key from ATTEST_SIGNING_KEY_ED25519 (base64 raw
    32 bytes), or None when unsigned operation is configured."""
    raw = os.environ.get("ATTEST_SIGNING_KEY_ED25519", "")
    if not raw:
        return None
    if raw == "demo":
        # The zero-credential judge path signs with a DELIBERATELY PUBLIC
        # deterministic key so certificates are still verifiable end to end;
        # production sets a real secret instead.
        return Ed25519PrivateKey.from_private_bytes(
            hashlib.sha256(b"attest-demo-signing-key").digest()
        )
    try:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw))
    except Exception:
        logging.getLogger(__name__).warning("invalid ATTEST_SIGNING_KEY_ED25519; serving unsigned")
        return None


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
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            # An unreadable audio dir must not masquerade as honest absence.
            logging.getLogger(__name__).warning(
                "audio dir stat failed for %s; check ATTEST_AUDIO_DIR permissions", run_id
            )
            return None
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


@app.get("/api/runs/{run_id}/attestation")
async def api_run_attestation(run_id: str) -> dict[str, object]:
    """A portable, verifiable record of one completed verification.

    Deterministic for a given run (timestamps come from the run row, never
    from the clock), so the signature is stable. The HMAC covers the
    canonical JSON of the document without its signature field; anyone
    holding the signing key can recompute and verify. Without a configured
    key the document still ships, honestly marked unsigned.
    """
    conn = db.connect(db.db_path())
    try:
        row = db.get_run(conn, run_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    if row["state"] != "completed":
        raise HTTPException(status_code=409, detail="attestation exists only for completed runs")

    analysis_doc = analysis.analyze_run(row)
    payload_sha = hashlib.sha256(str(row["terminal_payload"]).encode()).hexdigest()

    calibration: dict[str, object] = {"available": False}
    metrics_path = Path(os.environ.get("ATTEST_METRICS_PATH", "eval/results/metrics.json"))
    if metrics_path.exists():
        head = json.loads(metrics_path.read_text())["headline"]
        calibration = {
            "available": True,
            "qhat": head["qhat"],
            "target_coverage": head["target_coverage"],
            "empirical_coverage": head["empirical_coverage"],
            "provenance": "guarantee computed on scripted seeded personas, held-out fold",
        }

    doc: dict[str, object] = {
        "schema": "attest/attestation/v1",
        "run_id": str(row["run_id"]),
        "created_at": str(row["created_at"]),
        "completed_at": str(row["updated_at"]),
        "org": analysis_doc.get("org"),
        "replay": analysis_doc.get("replay", False),
        "claims": analysis_doc.get("claims"),
        "reconciliation": analysis_doc.get("reconciliation"),
        "calibration": calibration,
        "terminal_payload_sha256": payload_sha,
        "policy": (
            "every answer cites a verbatim transcript span; abstention is the "
            "calibrated conformal decision; nothing here was hand-edited"
        ),
    }
    doc = cast(dict[str, object], _jcs_numbers(doc))
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    private_key = _signing_key()
    if private_key is not None:
        signature = private_key.sign(canonical.encode())
        doc["signature"] = {
            "alg": "Ed25519",
            "signed": True,
            "value": base64.b64encode(signature).decode(),
            "public_key": "GET /api/attestation-key (PEM), also committed in the repo",
            "covers": (
                "canonical JSON (sorted keys, compact separators, "
                "unescaped unicode) of this document without the "
                "signature field"
            ),
        }
    else:
        doc["signature"] = {"alg": None, "signed": False, "value": None}
    return doc


@app.get("/api/attestation-key")
async def api_attestation_key() -> Response:
    """The Ed25519 public key that verifies every attestation this
    deployment signs. Anyone can check a certificate offline."""
    private_key = _signing_key()
    if private_key is None:
        raise HTTPException(status_code=404, detail="no signing key configured")
    pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return Response(content=pem, media_type="application/x-pem-file")


@app.get("/api/metrics")
async def api_metrics() -> dict[str, object]:
    metrics_path = Path(os.environ.get("ATTEST_METRICS_PATH", "eval/results/metrics.json"))
    if not metrics_path.exists():
        raise HTTPException(status_code=404, detail="metrics not generated")
    data: dict[str, object] = json.loads(metrics_path.read_text())
    real_path = Path(os.environ.get("ATTEST_REAL_CHANNEL_PATH", "eval/results/real_channel.json"))
    if real_path.exists():
        real = json.loads(real_path.read_text())
        # The per-call rows stay in the repo; the console needs the summary.
        real.pop("rows", None)
        data["real_channel"] = real
    return data


class StartRunRequest(BaseModel):
    phone: str = Field(pattern=r"^\+1\d{10}$")
    org: str = Field(min_length=2, max_length=120)
    claims: dict[str, str] = Field(default_factory=dict)
    consent: bool = False


def _caller_role(provided: str | None) -> str:
    """Fail closed: 503 when no key is configured, 403 on mismatch.

    Two credentials exist. The OPERATOR key (the builder) creates
    unrestricted runs. The JUDGE key exists so a judge can experience the
    product by having Attest call THEIR OWN phone: every judge run is
    consent-checked, self-requested, capped, and deduplicated."""
    operator = os.environ.get("ATTEST_OPERATOR_KEY", "")
    judge = os.environ.get("ATTEST_JUDGE_KEY", "")
    if not operator and not judge:
        raise HTTPException(status_code=503, detail="run creation unavailable")
    if provided is not None and operator and hmac.compare_digest(provided, operator):
        return "operator"
    if provided is not None and judge and hmac.compare_digest(provided, judge):
        return "judge"
    raise HTTPException(status_code=403, detail="forbidden")


_SANDBOX_CAP = int(os.environ.get("ATTEST_SANDBOX_CAP", "15"))


def _enforce_sandbox_rails(body: StartRunRequest) -> str:
    """The judge sandbox dials ONLY the requester's own number, once, with
    explicit consent, under a global cap, behind a kill switch. Returns the
    phone hash used for deduplication."""
    if os.environ.get("ATTEST_SANDBOX_ENABLED", "1") == "0":
        raise HTTPException(status_code=503, detail="the live demo is currently disabled")
    if not body.consent:
        raise HTTPException(
            status_code=422,
            detail=(
                "consent required: confirm this is your own number and that "
                "you are requesting this call"
            ),
        )
    phone_hash = hashlib.sha256(body.phone.encode()).hexdigest()
    conn = db.connect(db.db_path())
    try:
        rows = conn.execute(
            "SELECT record_json FROM call_runs WHERE record_json LIKE ?",
            ('%"judge_sandbox": true%',),
        ).fetchall()
    finally:
        conn.close()
    if len(rows) >= _SANDBOX_CAP:
        raise HTTPException(
            status_code=429,
            detail="the live demo call budget is spent; the replays show real runs",
        )
    for row in rows:
        record = json.loads(str(row[0]))
        if record.get("judge_phone_hash") == phone_hash:
            raise HTTPException(
                status_code=429,
                detail="this number already received its demo call",
            )
    return phone_hash


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
    role = _caller_role(x_attest_key)
    record: dict[str, object] = {"org": body.org, "claims": body.claims}
    if role == "judge":
        phone_hash = _enforce_sandbox_rails(body)
        record["judge_sandbox"] = True
        record["judge_phone_hash"] = phone_hash
        record["org"] = f"{body.org} (self-requested demo)"
    # The disclosure-first task is built server-side: no client can submit a
    # call script with the disclosure removed.
    task = runs.build_task(str(record["org"]), body.claims)
    async with _submission_lock:
        run_id = await runs.start_verification_run(
            _get_service(), db.db_path(), task=task, phone=body.phone, record=record
        )
    # Fresh submissions poll immediately instead of waiting out idle backoff.
    poller = getattr(app.state, "poller", None)
    if poller is not None:
        poller.wake()
    return {"run_id": run_id}
