"""Raw webhook capture probe. Operator-run only; never in CI.

Answers empirically what CALL-E actually delivers to webhook_url: method,
every header (signature? timestamp?), and the exact raw body. Findings feed
the verification posture; the capture file is gitignored.

    uv run python scripts/webhook_probe.py   # listens on :8787
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI()
OUT = Path("data/webhook-capture")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "HEAD"])
async def capture(request: Request, path: str) -> dict[str, str]:
    raw = await request.body()
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%H%M%S-%f")
    record = {
        "method": request.method,
        "path": "/" + path,
        "headers": dict(request.headers),
        "body_utf8": raw.decode("utf-8", errors="replace"),
    }
    (OUT / f"capture-{stamp}.json").write_text(json.dumps(record, indent=2))
    print(f"captured {request.method} /{path} ({len(raw)} bytes) -> capture-{stamp}.json")
    return {"received": "true"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="warning")
