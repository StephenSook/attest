"""The loop: submit, poll, terminal write, race, and resume-after-kill."""

import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from app import db, runs
from app.calle.client import CalleService
from app.calle.poller import Poller

BASE = "https://calle.test"
FIXTURE = json.loads(
    (Path(__file__).parent.parent / "mock_calle" / "fixtures" / "terminal_result.json").read_text()
)


def _service() -> CalleService:
    return CalleService(api_key="test-key-not-real", base_url=BASE)


def _pending_fixture() -> dict[str, object]:
    pending = dict(FIXTURE)
    pending["status"] = "queued"
    return pending


@respx.mock
async def test_full_loop_submit_poll_complete(tmp_path: Path) -> None:
    database = tmp_path / "loop.db"
    respx.post(f"{BASE}/v1/calls").mock(return_value=Response(201, json=_pending_fixture()))
    respx.get(f"{BASE}/v1/calls/{FIXTURE['id']}").mock(return_value=Response(200, json=FIXTURE))

    service = _service()
    run_id = await runs.start_verification_run(
        service, database, task="verify listing", phone="+15550101234"
    )
    conn = db.connect(database)
    row = db.get_run(conn, run_id)
    assert row is not None and row["state"] == "submitted"
    conn.close()

    poller = Poller(service, database)
    advanced = await poller.tick()
    assert advanced == 1

    conn = db.connect(database)
    row = db.get_run(conn, run_id)
    assert row is not None and row["state"] == "completed"
    payload = json.loads(str(row["terminal_payload"]))
    assert payload["task_completed"] is True
    conn.close()
    service.close()


@respx.mock
async def test_resume_after_kill_new_poller_picks_up_submitted_run(tmp_path: Path) -> None:
    """Simulates the restart: state lives in SQLite, a brand-new poller
    instance (new process) finds the submitted run and completes it."""
    database = tmp_path / "resume.db"
    respx.post(f"{BASE}/v1/calls").mock(return_value=Response(201, json=_pending_fixture()))
    respx.get(f"{BASE}/v1/calls/{FIXTURE['id']}").mock(return_value=Response(200, json=FIXTURE))

    first_service = _service()
    run_id = await runs.start_verification_run(
        first_service, database, task="verify listing", phone="+15550101234"
    )
    first_service.close()  # the "killed" process

    fresh_service = _service()
    fresh_poller = Poller(fresh_service, database)
    assert await fresh_poller.tick() == 1
    conn = db.connect(database)
    row = db.get_run(conn, run_id)
    assert row is not None and row["state"] == "completed"
    conn.close()
    fresh_service.close()


def test_webhook_vs_poller_race_second_write_noops(tmp_path: Path) -> None:
    database = tmp_path / "race.db"
    conn = db.connect(database)
    db.create_run(conn, run_id="run_race", idempotency_key="run_race")
    db.set_calle_call_id(conn, "run_race", str(FIXTURE["id"]))
    from app import fsm

    fsm.advance(conn, "run_race", "submitted")
    conn.close()

    first = runs.apply_terminal_payload(database, FIXTURE)
    second = runs.apply_terminal_payload(database, FIXTURE)
    assert first is True
    assert second is False


def test_non_terminal_payload_is_ignored(tmp_path: Path) -> None:
    database = tmp_path / "ignore.db"
    assert runs.apply_terminal_payload(database, {"id": "call_x", "status": "queued"}) is False


@respx.mock
async def test_submit_failure_marks_run_failed(tmp_path: Path) -> None:
    database = tmp_path / "fail.db"
    respx.post(f"{BASE}/v1/calls").mock(
        return_value=Response(400, json={"error": {"code": "bad", "message": "nope"}})
    )
    service = _service()
    with pytest.raises(Exception):  # noqa: B017 - any seam error is fine here
        await runs.start_verification_run(
            service, database, task="verify listing", phone="+15550101234"
        )
    conn = db.connect(database)
    rows = list(conn.execute("SELECT state FROM call_runs"))
    assert len(rows) == 1 and rows[0]["state"] == "failed"
    conn.close()
    service.close()
