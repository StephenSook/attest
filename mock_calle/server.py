"""Standalone mock of the CALL-E API surface.

Every automated test runs against this server. No test ever dials a real number.

The terminal payload in fixtures/terminal_result.json is a SCRUBBED REAL
payload captured from the 2026-07-25 probe call (phone and identifiers
replaced with reserved fictional values, conversation verbatim). It is test
infrastructure, never demo material.
"""

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException

app = FastAPI(title="mock-calle", version="0.1.0")

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "terminal_result.json"

# In-memory state: idempotency key -> call id, call id -> call record.
_calls_by_key: dict[str, str] = {}
_calls: dict[str, dict[str, Any]] = {}


def _load_fixture() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_FIXTURE_PATH.read_text())
    return data


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "mock-calle"}


@app.post("/v1/calls", status_code=201)
async def create_call(
    body: dict[str, Any],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    if idempotency_key and idempotency_key in _calls_by_key:
        call_id = _calls_by_key[idempotency_key]
        return _calls[call_id]

    call_id = f"call_mock_{uuid.uuid4().hex[:12]}"
    record = _load_fixture()
    record["id"] = call_id
    record["request"] = {
        "task": body.get("task"),
        "recipient": body.get("recipient"),
        "metadata": body.get("metadata", {}),
    }
    _calls[call_id] = record
    if idempotency_key:
        _calls_by_key[idempotency_key] = call_id
    return record


@app.get("/v1/calls/{call_id}")
async def get_call(call_id: str) -> dict[str, Any]:
    if call_id not in _calls:
        raise HTTPException(status_code=404, detail="call not found")
    return _calls[call_id]


@app.get("/v1/calls/{call_id}/events")
async def get_call_events(call_id: str) -> dict[str, Any]:
    # The real events-endpoint shape has not been probed yet; the terminal
    # payload itself carries no events array. Empty list until probed.
    if call_id not in _calls:
        raise HTTPException(status_code=404, detail="call not found")
    return {"events": []}
