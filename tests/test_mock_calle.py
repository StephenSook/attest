import httpx

from mock_calle.server import app as mock_app


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=mock_app)
    return httpx.AsyncClient(transport=transport, base_url="http://mock")


async def test_create_call_returns_terminal_record() -> None:
    async with _client() as client:
        response = await client.post(
            "/v1/calls",
            json={"task": "verify accepting new patients", "recipient": "+15550101234"},
            headers={"Idempotency-Key": "test-key-1"},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert body["id"].startswith("call_mock_")
    assert body["task_completed"] is True
    turns = body["recipients"][0]["attempts"][0]["transcript_turns"]
    assert turns[0]["speaker"] == "bot"
    assert any(turn["speaker"] == "user" for turn in turns)


async def test_idempotency_key_returns_same_call() -> None:
    async with _client() as client:
        first = await client.post(
            "/v1/calls",
            json={"task": "verify", "recipient": "+15550101234"},
            headers={"Idempotency-Key": "test-key-dup"},
        )
        second = await client.post(
            "/v1/calls",
            json={"task": "verify", "recipient": "+15550101234"},
            headers={"Idempotency-Key": "test-key-dup"},
        )
    assert first.json()["id"] == second.json()["id"]


async def test_get_call_and_events_roundtrip() -> None:
    async with _client() as client:
        created = await client.post(
            "/v1/calls",
            json={"task": "verify", "recipient": "+15550101234"},
            headers={"Idempotency-Key": "test-key-2"},
        )
        call_id = created.json()["id"]
        fetched = await client.get(f"/v1/calls/{call_id}")
        events = await client.get(f"/v1/calls/{call_id}/events")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == call_id
    assert events.status_code == 200
    assert events.json()["events"] == []


async def test_get_unknown_call_is_404() -> None:
    async with _client() as client:
        response = await client.get("/v1/calls/call_mock_does_not_exist")
    assert response.status_code == 404
