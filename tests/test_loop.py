"""The loop: submit, poll, terminal write, race, and retry-after-kill."""

import asyncio
import hashlib
import json
import multiprocessing
import os
import time
from pathlib import Path
from typing import Any, cast

import pytest
import respx
from calle.errors import CalleAPIError
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


class _CrashAfterAcceptanceService:
    """Stateful fake that dies after remote acceptance but before returning."""

    def __init__(self, marker: Path) -> None:
        self._marker = marker

    def dispatch_identity(self) -> dict[str, Any]:
        return {
            "base_url": "stateful://call-provider",
            "provider": "live",
            "credential_fingerprint": "stateful-test-credential",
        }

    def dispatch_digest(self, canonical_request: str) -> str:
        return hashlib.sha256(("stateful-test-key:" + canonical_request).encode()).hexdigest()

    async def place_call(
        self,
        *,
        task: str,
        phone: str,
        idempotency_key: str,
        webhook_url: str | None = None,
    ) -> dict[str, Any]:
        self._marker.write_text(
            json.dumps(
                {
                    "call_id": "call_process_boundary_1",
                    "idempotency_key": idempotency_key,
                    "phone": phone,
                    "task": task,
                    "webhook_url": webhook_url,
                },
                sort_keys=True,
            )
        )
        os._exit(73)


class _StatefulRetryService:
    """Returns the original logical call only for the identical retry."""

    def __init__(self, marker: Path) -> None:
        self._marker = marker

    def dispatch_identity(self) -> dict[str, Any]:
        return {
            "base_url": "stateful://call-provider",
            "provider": "live",
            "credential_fingerprint": "stateful-test-credential",
        }

    def dispatch_digest(self, canonical_request: str) -> str:
        return hashlib.sha256(("stateful-test-key:" + canonical_request).encode()).hexdigest()

    async def place_call(
        self,
        *,
        task: str,
        phone: str,
        idempotency_key: str,
        webhook_url: str | None = None,
    ) -> dict[str, Any]:
        accepted = json.loads(self._marker.read_text())
        assert accepted["idempotency_key"] == idempotency_key
        assert accepted["phone"] == phone
        assert accepted["task"] == task
        assert accepted["webhook_url"] == webhook_url
        accepted["retry_count"] = 1
        self._marker.write_text(json.dumps(accepted, sort_keys=True))
        return {"id": accepted["call_id"], "status": "queued"}


def _crash_after_acceptance_worker(database_text: str, marker_text: str) -> None:
    runs.DISPATCH_LEASE_SECONDS = 0.05
    service = cast(CalleService, _CrashAfterAcceptanceService(Path(marker_text)))
    asyncio.run(
        runs.start_verification_run(
            service,
            Path(database_text),
            task="verify listing",
            phone="+15550101234",
            record={"provider": "live"},
            run_id="run_process_crash",
        )
    )


def _retry_after_crash_worker(database_text: str, marker_text: str) -> None:
    service = cast(CalleService, _StatefulRetryService(Path(marker_text)))

    async def retry() -> None:
        await runs.start_verification_run(
            service,
            Path(database_text),
            task="verify listing",
            phone="+15550101234",
            record={"provider": "live"},
            run_id="run_process_crash",
        )
        assert runs.apply_terminal_payload(
            Path(database_text),
            {"id": "call_process_boundary_1", "status": "completed"},
        )

    asyncio.run(retry())


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


@pytest.mark.parametrize(
    ("poll_api_key", "poll_base_url"),
    [
        ("rotated-key", BASE),
        ("test-key-not-real", "https://different-provider.test"),
    ],
)
@respx.mock
async def test_restart_does_not_poll_through_changed_transport(
    tmp_path: Path,
    poll_api_key: str,
    poll_base_url: str,
) -> None:
    database = tmp_path / "transport-bound-poll.db"
    respx.post(f"{BASE}/v1/calls").mock(return_value=Response(201, json=_pending_fixture()))
    changed_get = respx.get(f"{poll_base_url}/v1/calls/{FIXTURE['id']}").mock(
        return_value=Response(200, json=FIXTURE)
    )
    first_service = _service()
    run_id = await runs.start_verification_run(
        first_service, database, task="verify listing", phone="+15550101234"
    )
    first_service.close()

    changed_service = CalleService(api_key=poll_api_key, base_url=poll_base_url)
    try:
        poller = Poller(changed_service, database)
        assert await poller.tick() == 0
        assert poller.healthy is False
        assert poller.blocked_run_count == 1
    finally:
        changed_service.close()
    assert changed_get.call_count == 0
    conn = db.connect(database)
    try:
        row = db.get_run(conn, run_id)
        assert row is not None and row["state"] == "submitted"
        assert json.loads(str(row["terminal_payload"]))["stage"] == ("transport_identity_mismatch")
    finally:
        conn.close()


@respx.mock
async def test_poll_exhaustion_keeps_destination_reserved_until_late_terminal(
    tmp_path: Path,
) -> None:
    database = tmp_path / "poll-exhausted.db"
    service = _service()
    identity = service.dispatch_identity()
    conn = db.connect(database)
    try:
        db.create_run(conn, run_id="run_poll_exhausted", idempotency_key="run_poll_exhausted")
        assert db.claim_submission_attempt(
            conn,
            "run_poll_exhausted",
            dispatch_digest="a" * 64,
            dispatch_base_url=str(identity["base_url"]),
            dispatch_provider=str(identity["provider"]),
            dispatch_credential_fingerprint=str(identity["credential_fingerprint"]),
            destination_hash="destination-a",
            lease_owner="owner-a",
        ) == ("claimed", 1)
        assert db.accept_submission(conn, "run_poll_exhausted", str(FIXTURE["id"]))
    finally:
        conn.close()

    route = respx.get(f"{BASE}/v1/calls/{FIXTURE['id']}").mock(
        side_effect=[
            *[
                Response(503, json={"error": {"code": "unavailable", "message": "retry"}})
                for _ in range(5)
            ],
            Response(200, json=FIXTURE),
        ]
    )
    poller = Poller(service, database)
    for _ in range(5):
        assert await poller.tick() == 0

    conn = db.connect(database)
    try:
        blocked = db.get_run(conn, "run_poll_exhausted")
        assert blocked is not None and blocked["state"] == "submitted"
        assert json.loads(str(blocked["terminal_payload"]))["stage"] == "poll_exhausted"
        assert poller.blocked_run_count == 1
        assert (
            db.create_request_run(
                conn,
                run_id="run_duplicate_destination",
                idempotency_key="run_duplicate_destination",
                record_json="{}",
                destination_hash="destination-a",
            )
            == "destination_blocked"
        )
    finally:
        conn.close()

    assert await poller.tick() == 1
    conn = db.connect(database)
    try:
        completed = db.get_run(conn, "run_poll_exhausted")
        assert completed is not None and completed["state"] == "completed"
        assert (
            db.create_request_run(
                conn,
                run_id="run_after_terminal",
                idempotency_key="run_after_terminal",
                record_json="{}",
                destination_hash="destination-a",
            )
            == "ok"
        )
    finally:
        conn.close()
        service.close()
    assert route.call_count == 6


def test_same_request_recovers_acceptance_lost_at_process_boundary(tmp_path: Path) -> None:
    """Two spawned interpreters exercise the real accepted-before-SQLite boundary."""
    database = tmp_path / "accepted-remotely.db"
    marker = tmp_path / "provider-state.json"
    context = multiprocessing.get_context("spawn")
    first = context.Process(
        target=_crash_after_acceptance_worker,
        args=(str(database), str(marker)),
    )
    first.start()
    first.join(10)
    assert not first.is_alive()
    assert first.exitcode == 73

    # The first process owned a 50 ms lease. Its death releases the OS lock,
    # then the bounded lease expires so another process can safely reuse the
    # exact request identity.
    time.sleep(0.08)
    second = context.Process(
        target=_retry_after_crash_worker,
        args=(str(database), str(marker)),
    )
    second.start()
    second.join(10)
    assert not second.is_alive()
    assert second.exitcode == 0

    conn = db.connect(database)
    try:
        recovered = db.get_run(conn, "run_process_crash")
        assert recovered is not None and recovered["state"] == "completed"
        assert recovered["calle_call_id"] == "call_process_boundary_1"
        assert recovered["submit_attempts"] == 2
    finally:
        conn.close()
    provider_state = json.loads(marker.read_text())
    assert provider_state["idempotency_key"] == "run_process_crash"
    assert provider_state["retry_count"] == 1
    persisted = b"".join(path.read_bytes() for path in tmp_path.glob("accepted-remotely.db*"))
    assert b"+15550101234" not in persisted


@respx.mock
async def test_expired_unknown_dispatch_is_failed_without_a_late_call(tmp_path: Path) -> None:
    database = tmp_path / "expired-dispatch.db"
    run_id = "run_expired_dispatch"
    create_route = respx.post(f"{BASE}/v1/calls").mock(
        side_effect=[
            Response(500, json={"error": {"code": "unknown", "message": "try again"}}),
            Response(201, json=_pending_fixture()),
        ]
    )
    service = _service()
    with pytest.raises(Exception):  # noqa: B017 - provider seam error is expected
        await runs.start_verification_run(
            service,
            database,
            task="verify listing",
            phone="+15550101234",
            run_id=run_id,
        )
    conn = db.connect(database)
    conn.execute(
        "UPDATE call_runs SET dispatch_expires_at = 0, submit_lease_until = 0 WHERE run_id = ?",
        (run_id,),
    )
    conn.commit()
    conn.close()

    with pytest.raises(runs.CallSubmissionExpired):
        await runs.start_verification_run(
            service,
            database,
            task="verify listing",
            phone="+15550101234",
            run_id=run_id,
        )
    service.close()

    conn = db.connect(database)
    try:
        expired = db.get_run(conn, run_id)
        assert expired is not None and expired["state"] == "failed"
        payload = json.loads(str(expired["terminal_payload"]))
        assert payload["stage"] == "submit_recovery_expired"
    finally:
        conn.close()
    assert create_route.call_count == 1


def test_owner_lease_blocks_rivals_and_expiry_waits_for_the_owner(tmp_path: Path) -> None:
    database = tmp_path / "lease.db"
    conn = db.connect(database)
    try:
        db.create_run(conn, run_id="run_lease", idempotency_key="run_lease")
        assert db.claim_submission_attempt(
            conn,
            "run_lease",
            dispatch_digest="a" * 64,
            dispatch_base_url=BASE,
            dispatch_provider="live",
            dispatch_credential_fingerprint="credential-a",
            destination_hash="destination-a",
            lease_owner="owner-a",
            now=100,
            lease_seconds=120,
            recovery_window_seconds=10,
        ) == ("claimed", 1)
        assert db.claim_submission_attempt(
            conn,
            "run_lease",
            dispatch_digest="a" * 64,
            dispatch_base_url=BASE,
            dispatch_provider="live",
            dispatch_credential_fingerprint="credential-a",
            destination_hash="destination-a",
            lease_owner="owner-b",
            now=111,
            lease_seconds=120,
            recovery_window_seconds=10,
        ) == ("busy", 1)
        assert db.release_submission_lease(conn, "run_lease", "owner-b") is False
        assert db.expire_submission_attempts(conn, now=111) == 0
        active = db.get_run(conn, "run_lease")
        assert active is not None and active["state"] == "created"
        assert db.release_submission_lease(conn, "run_lease", "owner-a") is True
        assert db.expire_submission_attempts(conn, now=111) == 1
        expired = db.get_run(conn, "run_lease")
        assert expired is not None and expired["state"] == "failed"
    finally:
        conn.close()


def test_stale_rejection_cannot_clear_newer_owner_or_reservation(tmp_path: Path) -> None:
    database = tmp_path / "stale-rejection.db"
    conn = db.connect(database)
    try:
        assert (
            db.create_sandbox_run(
                conn,
                phone_hash="phone-a",
                cap=1,
                run_id="run_stale",
                idempotency_key="run_stale",
                record_json="{}",
            )
            == "ok"
        )
        identity = {
            "dispatch_digest": "a" * 64,
            "dispatch_base_url": BASE,
            "dispatch_provider": "live",
            "dispatch_credential_fingerprint": "credential-a",
            "destination_hash": "phone-a",
        }
        assert db.claim_submission_attempt(
            conn,
            "run_stale",
            **identity,
            lease_owner="owner-a",
            now=100,
            lease_seconds=1,
            recovery_window_seconds=100,
        ) == ("claimed", 1)
        assert db.claim_submission_attempt(
            conn,
            "run_stale",
            **identity,
            lease_owner="owner-b",
            now=102,
            lease_seconds=30,
            recovery_window_seconds=100,
        ) == ("claimed", 2)
        assert (
            db.reject_submission(
                conn,
                "run_stale",
                '{"stage":"submit"}',
                lease_owner="owner-a",
                attempt_number=1,
                sandbox_phone_hash="phone-a",
            )
            is False
        )
        row = db.get_run(conn, "run_stale")
        assert row is not None and row["state"] == "created"
        assert row["submit_lease_owner"] == "owner-b"
        assert conn.execute("SELECT COUNT(*) FROM sandbox_reservations").fetchone()[0] == 1
        assert db.accept_submission(conn, "run_stale", "call_new_owner") is True
    finally:
        conn.close()


@respx.mock
async def test_retry_cannot_cross_provider_endpoint_identity(tmp_path: Path) -> None:
    database = tmp_path / "provider-bound.db"
    first_route = respx.post(f"{BASE}/v1/calls").mock(
        return_value=Response(500, json={"error": {"code": "unknown", "message": "retry"}})
    )
    other_base = "https://different-provider.test"
    other_route = respx.post(f"{other_base}/v1/calls").mock(
        return_value=Response(201, json=_pending_fixture())
    )
    first_service = _service()
    with pytest.raises(CalleAPIError):
        await runs.start_verification_run(
            first_service,
            database,
            task="verify listing",
            phone="+15550101234",
            run_id="run_provider_bound",
        )
    changed_service = CalleService(api_key="test-key-not-real", base_url=other_base)
    with pytest.raises(RuntimeError, match="cannot change its destination or provider"):
        await runs.start_verification_run(
            changed_service,
            database,
            task="verify listing",
            phone="+15550101234",
            run_id="run_provider_bound",
        )
    rotated_service = CalleService(api_key="rotated-key", base_url=BASE)
    with pytest.raises(RuntimeError, match="cannot change its destination or provider"):
        await runs.start_verification_run(
            rotated_service,
            database,
            task="verify listing",
            phone="+15550101234",
            run_id="run_provider_bound",
        )
    first_service.close()
    changed_service.close()
    rotated_service.close()
    assert first_route.call_count == 1
    assert other_route.call_count == 0


@respx.mock
async def test_later_4xx_cannot_erase_a_possibly_accepted_first_attempt(tmp_path: Path) -> None:
    database = tmp_path / "ambiguous-then-401.db"
    run_id = "run_ambiguous_then_401"
    phone_hash = "phone-hash"
    conn = db.connect(database)
    assert (
        db.create_sandbox_run(
            conn,
            phone_hash=phone_hash,
            cap=1,
            run_id=run_id,
            idempotency_key=run_id,
            record_json=json.dumps({"provider": "live"}),
        )
        == "ok"
    )
    conn.close()
    route = respx.post(f"{BASE}/v1/calls").mock(
        side_effect=[
            Response(500, json={"error": {"code": "unknown", "message": "retry"}}),
            Response(401, json={"error": {"code": "unauthorized", "message": "rotated"}}),
        ]
    )
    service = _service()
    for _ in range(2):
        with pytest.raises(CalleAPIError):
            await runs.start_verification_run(
                service,
                database,
                task="verify listing",
                phone="+15550101234",
                run_id=run_id,
                sandbox_phone_hash=phone_hash,
                destination_hash=phone_hash,
            )
    service.close()

    conn = db.connect(database)
    try:
        row = db.get_run(conn, run_id)
        assert row is not None and row["state"] == "created"
        assert row["submit_attempts"] == 2
        assert conn.execute("SELECT COUNT(*) FROM sandbox_reservations").fetchone()[0] == 1
    finally:
        conn.close()
    assert route.call_count == 2


@respx.mock
async def test_poller_recovers_created_run_that_already_has_a_call_id(tmp_path: Path) -> None:
    """Recover the legacy partial-commit shape without stranding the real call."""
    database = tmp_path / "accepted-before-transition.db"
    service = _service()
    identity = service.dispatch_identity()
    conn = db.connect(database)
    db.create_run(conn, run_id="run_partial", idempotency_key="run_partial")
    assert db.claim_submission_attempt(
        conn,
        "run_partial",
        dispatch_digest="a" * 64,
        dispatch_base_url=str(identity["base_url"]),
        dispatch_provider=str(identity["provider"]),
        dispatch_credential_fingerprint=str(identity["credential_fingerprint"]),
        destination_hash="destination-a",
        lease_owner="owner-a",
    ) == ("claimed", 1)
    db.set_calle_call_id(conn, "run_partial", str(FIXTURE["id"]))
    row = db.get_run(conn, "run_partial")
    assert row is not None and row["state"] == "created"
    conn.close()

    respx.get(f"{BASE}/v1/calls/{FIXTURE['id']}").mock(return_value=Response(200, json=FIXTURE))
    poller = Poller(service, database)
    assert await poller.tick() == 1

    conn = db.connect(database)
    try:
        recovered = db.get_run(conn, "run_partial")
        assert recovered is not None and recovered["state"] == "completed"
    finally:
        conn.close()
        service.close()


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


def test_late_ambiguous_submit_cannot_replace_completed_evidence(tmp_path: Path) -> None:
    database = tmp_path / "late-submit-error.db"
    conn = db.connect(database)
    db.create_run(conn, run_id="run_late", idempotency_key="run_late")
    db.accept_submission(conn, "run_late", str(FIXTURE["id"]))
    from app import fsm

    terminal_payload = json.dumps(FIXTURE)
    fsm.advance(conn, "run_late", "completed", terminal_payload=terminal_payload)

    assert (
        db.set_submit_error(
            conn,
            "run_late",
            json.dumps({"error": "late timeout", "stage": "submit_ambiguous"}),
        )
        is False
    )
    row = db.get_run(conn, "run_late")
    assert row is not None and row["state"] == "completed"
    assert row["terminal_payload"] == terminal_payload
    conn.close()


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
