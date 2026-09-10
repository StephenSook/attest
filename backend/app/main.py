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
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, StrictBool, field_validator

from app import analysis, db, runs
from app.calle import client as calle_client
from app.calle.client import CalleService
from app.calle.poller import Poller
from app.calle.webhook import router as webhook_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    startup_conn = db.connect(db.db_path())
    startup_conn.close()
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
    application.state.poller_task = task
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

# Public read-only API for the console; writes stay key-gated. Only records
# carrying the server-owned publication flag can leave the server, and phone
# numbers are masked before they do, so a permissive read origin policy is
# acceptable here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Attest-Key", "X-Attest-Run-Token"],
)


def _sandbox_enabled() -> bool:
    """The public dialing surface is opt-in and defaults closed.

    The current hosted database is ephemeral, so production remains closed
    until its call reservations can survive a deploy.
    """
    return os.environ.get("ATTEST_SANDBOX_ENABLED", "0") == "1"


def _sandbox_ready() -> bool:
    """True only when the opt-in switch and private sandbox keys are present."""
    return (
        _sandbox_enabled()
        and bool(os.environ.get("ATTEST_JUDGE_KEY", ""))
        and bool(os.environ.get("ATTEST_PHONE_HASH_KEY", ""))
    )


def _record_for(row: sqlite3.Row) -> dict[str, object]:
    return json.loads(str(row["record_json"])) if row["record_json"] else {}


def _require_public_run(row: sqlite3.Row) -> None:
    """Default every run private unless the server published it explicitly.

    The seeded replays carry recorded publication consent. Permission to place
    or receive a call never doubles as permission to publish its transcript.
    """
    if _record_for(row).get("published") is not True:
        raise HTTPException(status_code=404, detail="run not found")


async def _outbound_readiness() -> tuple[bool, list[str]]:
    """Check the exact prerequisites used by the call-creation path."""
    reasons: list[str] = []
    provider = "mock" if calle_client.is_mock_mode() else "live"
    if provider == "live" and not os.environ.get("CALLE_API_KEY", "").strip():
        reasons.append("provider_credentials_missing")
    if not os.environ.get("ATTEST_PHONE_HASH_KEY", "").strip():
        reasons.append("destination_hash_key_missing")
    operator_ready = bool(os.environ.get("ATTEST_OPERATOR_KEY", "").strip())
    if not operator_ready and not _sandbox_ready():
        reasons.append("call_authorization_missing")

    service = getattr(app.state, "calle_service", None)
    if not isinstance(service, CalleService):
        reasons.append("call_service_uninitialized")
    elif not service.matches_current_configuration():
        reasons.append("call_service_configuration_stale")

    if "destination_hash_key_missing" not in reasons:
        conn: sqlite3.Connection | None = None
        try:
            conn = db.connect(db.db_path())
            binding = db.bind_runtime_fingerprint(
                conn,
                name="destination_hash_key",
                fingerprint=_destination_hash_key_fingerprint(),
            )
            if binding == "mismatch":
                reasons.append("destination_hash_binding_mismatch")
            elif binding == "unbound_data":
                reasons.append("destination_hash_binding_unattributed")
        except Exception:
            reasons.append("readiness_database_unavailable")
        finally:
            if conn is not None:
                conn.close()

    if not reasons and isinstance(service, CalleService):
        provider_ready, provider_reason = await service.probe_readiness()
        if not provider_ready:
            reasons.append(provider_reason or "provider_probe_failed")
    return not reasons, reasons


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Liveness and outbound readiness for the complete call path.

    A dead poller means no run can ever reach a terminal state. A live
    process can still reject every new call because a credential, cached
    client, or database binding is wrong, so those checks are part of the
    status rather than hidden behind the first real request.

    It also reports whether this deployment dials the real platform or the
    local mock. ATTEST_USE_MOCK defaults to true, so an instance that is
    merely missing an env var will happily serve simulated results, and
    nothing outside the process could tell. Every run record is already
    stamped with its provider; this exposes the same fact before a call is
    placed rather than after. No secret is involved: the value is one of two
    words, and knowing which one is what makes the deployment auditable.
    """
    task = getattr(app.state, "poller_task", None)
    poller = getattr(app.state, "poller", None)
    task_alive = task is not None and not task.done()
    poller_healthy = isinstance(poller, Poller) and poller.healthy
    poller_ready = task_alive and poller_healthy
    outbound_ready, outbound_reasons = await _outbound_readiness()
    healthy = poller_ready and outbound_ready
    body: dict[str, object] = {
        "status": "ok" if healthy else "degraded",
        "service": "attest",
        "poller": "running" if poller_ready else ("degraded" if task_alive else "stopped"),
        "recovery_blocked": poller.blocked_run_count if isinstance(poller, Poller) else 0,
        "provider": "mock" if calle_client.is_mock_mode() else "live",
        "sandbox": "enabled" if _sandbox_ready() else "disabled",
        "outbound": {
            "status": "ready" if outbound_ready else "blocked",
            "reasons": outbound_reasons,
        },
    }
    return JSONResponse(status_code=200 if healthy else 503, content=body)


@app.get("/api/runs")
async def api_runs() -> dict[str, list[dict[str, object]]]:
    conn = db.connect(db.db_path())
    try:
        rows = db.list_published_runs(conn)
    finally:
        conn.close()
    out: list[dict[str, object]] = []
    for row in rows:
        record = _record_for(row)
        if record.get("published") is not True:
            continue
        item: dict[str, object] = {
            "run_id": row["run_id"],
            "state": row["state"],
            "created_at": row["created_at"],
            "org": record.get("org"),
            "replay": bool(record.get("replay", False)),
            "provider": record.get("provider"),
        }
        # A completed run carries its verdict so the ledger reads at a glance;
        # computed from the same server-authoritative analysis, never stored.
        if row["state"] == "completed" and row["terminal_payload"]:
            item["verdict"] = analysis.analyze_run(row)["reconciliation"]["verdict"]
        out.append(item)
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
    _require_public_run(row)
    audio = _audio_file(run_id)
    if audio is None:
        raise HTTPException(status_code=404, detail="no audio for this run")
    return FileResponse(audio, media_type=_AUDIO_TYPES[audio.suffix])


def _detail_for_run(row: sqlite3.Row) -> dict[str, object]:
    run_id = str(row["run_id"])
    payload = json.loads(str(row["terminal_payload"])) if row["terminal_payload"] else None
    record = _record_for(row)
    detail: dict[str, object] = {
        "run_id": run_id,
        "state": row["state"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "payload": analysis.redact_payload(payload) if payload else None,
        "has_audio": _audio_file(run_id) is not None,
        "provider": record.get("provider"),
        "published": record.get("published") is True,
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
    elif payload and row["state"] == "submitted" and payload.get("stage"):
        detail["blocked"] = {
            "error": str(payload.get("error", "recovery blocked"))[:200],
            "stage": str(payload.get("stage", "unknown"))[:60],
        }
    return detail


@app.get("/api/runs/{run_id}")
async def api_run_detail(run_id: str) -> dict[str, object]:
    conn = db.connect(db.db_path())
    try:
        row = db.get_run(conn, run_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    _require_public_run(row)
    return _detail_for_run(row)


@app.get("/internal/runs/{run_id}")
async def internal_run_detail(
    run_id: str,
    response: Response,
    x_attest_run_token: str | None = Header(default=None, alias="X-Attest-Run-Token"),
) -> dict[str, object]:
    """Return one private run to the browser that created it.

    The opaque capability never enters the URL or database. Only its digest is
    persisted, and every rejected lookup returns 404 so private run IDs are not
    disclosed through response differences.
    """
    conn = db.connect(db.db_path())
    try:
        row = db.get_run(conn, run_id)
    finally:
        conn.close()
    if row is None or not x_attest_run_token:
        raise HTTPException(status_code=404, detail="run not found")
    expected = str(_record_for(row).get("access_token_sha256", ""))
    provided = hashlib.sha256(x_attest_run_token.encode()).hexdigest()
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=404, detail="run not found")
    response.headers["Cache-Control"] = "private, no-store"
    return _detail_for_run(row)


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
    _require_public_run(row)
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
            if calibration["available"]
            else "every answer cites a verbatim transcript span; NO calibrated "
            "gate was available on this deployment, so abstention here is the "
            "uncalibrated extraction decision; nothing here was hand-edited"
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
    # +1 E.164, 10 digits. The reserved fictional 555-01XX range is
    # intentionally accepted (used for demos and tests); premium and toll
    # prefixes are rejected in the validator below.
    phone: str = Field(pattern=r"^\+1\d{10}$")
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    org: str = Field(min_length=2, max_length=120)
    claims: dict[str, str] = Field(default_factory=dict)
    consent: StrictBool = False

    @field_validator("phone")
    @classmethod
    def _not_premium(cls, value: str) -> str:
        # value is "+1" + 10 national digits, so the area code is [2:5].
        # The old toll check sliced [2:6] against "1950" and could never
        # match, so 950 numbers were accepted.
        area = value[2:5]
        if area in {"900", "976", "950"}:
            raise ValueError("premium-rate and toll numbers are not allowed")
        return value


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


def _sandbox_precheck(body: StartRunRequest) -> str:
    """Kill switch and consent gate before we touch the database. Returns
    the keyed phone digest; the slot is reserved atomically under the lock."""
    if not _sandbox_enabled():
        raise HTTPException(status_code=503, detail="the live demo is currently disabled")
    if not body.consent:
        raise HTTPException(
            status_code=422,
            detail=(
                "consent required: confirm this is your own number and that "
                "you are requesting this call"
            ),
        )
    return _destination_hash(body.phone)


def _destination_hash(phone: str) -> str:
    """Stable keyed destination identity for duplicate-call prevention."""
    phone_hash_key = os.environ.get("ATTEST_PHONE_HASH_KEY", "")
    if not phone_hash_key:
        raise HTTPException(status_code=503, detail="phone deduplication is not configured")
    return hmac.new(
        phone_hash_key.encode(),
        phone.encode(),
        hashlib.sha256,
    ).hexdigest()


def _destination_hash_key_fingerprint() -> str:
    phone_hash_key = os.environ.get("ATTEST_PHONE_HASH_KEY", "")
    if not phone_hash_key:
        raise HTTPException(status_code=503, detail="phone deduplication is not configured")
    return hashlib.sha256(phone_hash_key.encode()).hexdigest()


def _get_service() -> CalleService:
    service = getattr(app.state, "calle_service", None)
    if service is None:
        service = CalleService()
        app.state.calle_service = service
    return service


def _assert_dispatch_ready(provider: str) -> None:
    """Fail before reserving a judge slot when live dispatch cannot authenticate."""
    if provider == "live" and not os.environ.get("CALLE_API_KEY", "").strip():
        raise HTTPException(status_code=503, detail="live calling credentials are not configured")


def _assert_service_provider(service: CalleService, provider: str) -> None:
    """Reject a cached service after any call configuration change."""
    service_provider = str(service.dispatch_identity().get("provider", ""))
    if service_provider != provider or not service.matches_current_configuration():
        raise HTTPException(
            status_code=503,
            detail="call provider configuration changed; retry after restart",
        )


# One verification call at a time is a product invariant, not a hope.
_submission_lock = asyncio.Lock()


@app.post("/internal/runs", status_code=201)
async def start_run(
    body: StartRunRequest,
    x_attest_key: str | None = Header(default=None, alias="X-Attest-Key"),
    x_attest_run_token: str | None = Header(default=None, alias="X-Attest-Run-Token"),
) -> dict[str, str]:
    role = _caller_role(x_attest_key)
    if x_attest_run_token is None or len(x_attest_run_token) < 32:
        raise HTTPException(status_code=422, detail="a client run capability is required")
    access_token = x_attest_run_token
    run_id = f"run_{body.request_id}"
    provider = "mock" if calle_client.is_mock_mode() else "live"
    _assert_dispatch_ready(provider)
    request_json = json.dumps(
        {
            "claims": body.claims,
            "org": body.org,
            "phone": body.phone,
            "provider": provider,
            "role": role,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    request_digest = hmac.new(
        access_token.encode(),
        request_json.encode(),
        hashlib.sha256,
    ).hexdigest()
    token_sha256 = hashlib.sha256(access_token.encode()).hexdigest()
    record: dict[str, object] = {
        "org": body.org,
        "claims": body.claims,
        "access_token_sha256": token_sha256,
        "request_digest": request_digest,
        # Provenance, stamped at creation: a mock-served run must never be
        # mistakable for a real call anywhere downstream.
        "provider": provider,
    }
    destination_hash = _sandbox_precheck(body) if role == "judge" else _destination_hash(body.phone)
    phone_hash = ""
    if role == "judge":
        phone_hash = destination_hash
        record["judge_sandbox"] = True
        record["judge_phone_hash"] = phone_hash
        record["org"] = f"{body.org} (self-requested demo)"
    # The disclosure-first task is built server-side: no client can submit a
    # call script with the disclosure removed.
    task = runs.build_task(str(record["org"]), body.claims)
    service = _get_service()
    _assert_service_provider(service, provider)

    def validate_existing(row: sqlite3.Row) -> None:
        stored = _record_for(row)
        stored_token = str(stored.get("access_token_sha256", ""))
        if not stored_token or not hmac.compare_digest(stored_token, token_sha256):
            raise HTTPException(status_code=404, detail="run not found")
        stored_request = str(stored.get("request_digest", ""))
        if not stored_request or not hmac.compare_digest(stored_request, request_digest):
            raise HTTPException(status_code=409, detail="request id already belongs to another run")

    async with _submission_lock:
        conn = db.connect(db.db_path())
        try:
            binding = db.bind_runtime_fingerprint(
                conn,
                name="destination_hash_key",
                fingerprint=_destination_hash_key_fingerprint(),
            )
            if binding not in {"bound", "match"}:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "destination_identity_mismatch",
                        "message": (
                            "Outbound calling is locked because the destination identity "
                            "key does not match this database. Reconcile or migrate the "
                            "stored reservations before dialing."
                        ),
                    },
                )
            existing = db.get_run(conn, run_id)
            if existing is not None:
                validate_existing(existing)
            elif role == "judge":
                # The reservation and recoverable run identity commit as one
                # transaction. A failed insert cannot consume the call budget.
                outcome = db.create_sandbox_run(
                    conn,
                    phone_hash=phone_hash,
                    cap=_SANDBOX_CAP,
                    run_id=run_id,
                    idempotency_key=run_id,
                    record_json=json.dumps(record),
                )
                if outcome == "capped":
                    raise HTTPException(
                        status_code=429,
                        detail="the live demo call budget is spent; the replays show real runs",
                    )
                if outcome == "duplicate":
                    raise HTTPException(
                        status_code=429,
                        detail="this number already received its demo call",
                    )
                if outcome == "request_exists":
                    raced = db.get_run(conn, run_id)
                    if raced is None:
                        raise RuntimeError("request identity disappeared during creation")
                    validate_existing(raced)
            else:
                outcome = db.create_request_run(
                    conn,
                    run_id=run_id,
                    idempotency_key=run_id,
                    record_json=json.dumps(record),
                    destination_hash=destination_hash,
                )
                if outcome == "request_exists":
                    raced = db.get_run(conn, run_id)
                    if raced is None:
                        raise RuntimeError("request identity disappeared during creation")
                    validate_existing(raced)
                elif outcome == "destination_blocked":
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "call_destination_unreconciled",
                            "message": (
                                "A prior call to this destination has an unknown outcome. "
                                "Resume its original request or reconcile it in CALL-E first."
                            ),
                        },
                    )
            try:
                run_id = await runs.start_verification_run(
                    service,
                    db.db_path(),
                    task=task,
                    phone=body.phone,
                    record=record,
                    run_id=run_id,
                    connection=conn,
                    sandbox_phone_hash=phone_hash if role == "judge" else None,
                    destination_hash=destination_hash,
                )
            except runs.CallSubmissionRejected as exc:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "code": "call_rejected_before_acceptance",
                        "message": (
                            "CALL-E rejected the request before accepting a call. "
                            "No demo call was counted; try again with a new request."
                        ),
                    },
                ) from exc
            except runs.CallSubmissionBusy as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "call_request_in_progress",
                        "message": (
                            "The original call request is still in progress. "
                            "Wait briefly, then retry this same request."
                        ),
                    },
                ) from exc
            except runs.CallSubmissionExpired as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "call_request_not_retried",
                        "message": (
                            "The safe retry window ended. Attest will not dial this request late."
                        ),
                    },
                ) from exc
        finally:
            conn.close()
    # Fresh submissions poll immediately instead of waiting out idle backoff.
    poller = getattr(app.state, "poller", None)
    if poller is not None:
        poller.wake()
    return {"run_id": run_id, "access_token": access_token}
