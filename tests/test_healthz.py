import httpx

from app.main import app


async def test_healthz_fails_closed_without_a_running_lifespan() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 503
    body = response.json()
    assert body["service"] == "attest"
    # Without a running lifespan there is no poller, and healthz must say so
    # rather than claiming a blanket ok.
    assert body["status"] == "degraded"
    assert body["poller"] == "stopped"
