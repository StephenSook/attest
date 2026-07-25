from pathlib import Path

import pytest

from app import db, fsm


def _conn(tmp_path: Path):  # type: ignore[no-untyped-def]
    conn = db.connect(tmp_path / "test.db")
    db.create_run(conn, run_id="run_1", idempotency_key="run_1")
    return conn


def test_happy_path_created_submitted_completed(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    assert fsm.advance(conn, "run_1", "submitted") is True
    assert fsm.advance(conn, "run_1", "completed", terminal_payload="{}") is True
    row = db.get_run(conn, "run_1")
    assert row is not None and row["state"] == "completed"


def test_illegal_transition_raises(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    with pytest.raises(fsm.TransitionError):
        fsm.advance(conn, "run_1", "completed")


def test_terminal_is_sticky_race_loser_noops(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    fsm.advance(conn, "run_1", "submitted")
    assert fsm.advance(conn, "run_1", "completed", terminal_payload='{"who": "webhook"}')
    assert fsm.advance(conn, "run_1", "failed", terminal_payload='{"who": "poller"}') is False
    row = db.get_run(conn, "run_1")
    assert row is not None and row["state"] == "completed"
    assert "webhook" in str(row["terminal_payload"])


def test_unknown_run_raises(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    with pytest.raises(fsm.TransitionError):
        fsm.advance(conn, "run_missing", "submitted")
