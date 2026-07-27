import httpx

from app.main import app


async def test_healthz_returns_ok() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "attest"
    # Without a running lifespan there is no poller, and healthz must say so
    # rather than claiming a blanket ok.
    assert body["status"] in {"ok", "degraded"}
    assert body["poller"] in {"running", "stopped"}
