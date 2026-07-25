"""Manual probe call. Operator-run only; never invoked by tests or CI.

Places ONE real CALL-E call to the operator's own phone (ATTEST_PROBE_PHONE)
through the integration seam, polls to the terminal state, and dumps the full
terminal payload to data/probe/ (gitignored) so it can be hand-scrubbed into
the mock fixture.

Usage:
    set -a && source .env && set +a
    uv run python scripts/probe_call.py
"""

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from app.calle import CalleService

PROD_BASE_URL = "https://api.heycall-e.com"
POLL_SECONDS = 5.0
TIMEOUT_SECONDS = 600.0
TERMINAL = {"completed", "failed", "canceled"}

TASK = (
    "You are placing a consented systems test call on behalf of Stephen, a software "
    "developer testing his own phone verification integration. The person answering IS "
    "Stephen and has consented to this exact call. Open with: 'Hi, this is an automated "
    "assistant calling on behalf of Stephen for a consented test of his verification "
    "system. This call may be recorded.' Then ask one question: 'For the test, are you "
    "currently accepting new patients?' Record whatever they answer faithfully. If they "
    "ask to end the call, thank them and hang up immediately. Never guess: anything not "
    "stated gets recorded as unknown. Keep the whole call under two minutes."
)


async def main() -> None:
    phone = os.environ.get("ATTEST_PROBE_PHONE", "")
    api_key = os.environ.get("CALLE_API_KEY", "")
    if not phone or not api_key:
        sys.exit("Set CALLE_API_KEY and ATTEST_PROBE_PHONE in the environment first.")

    service = CalleService(api_key=api_key, base_url=PROD_BASE_URL)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    # No result_schema: the live API rejects both schema params today (see the
    # seam comment). The default summary/transcript payload is what we probe.
    created = await service.place_call(
        task=TASK,
        phone=phone,
        idempotency_key=f"attest-probe-{stamp}",
        metadata={"purpose": "probe", "budget_line": "probe"},
    )
    call_id = str(created.get("id", ""))
    print(f"created: id={call_id} status={created.get('status')}")

    call = created
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline and call.get("status") not in TERMINAL:
        await asyncio.sleep(POLL_SECONDS)
        call = await service.get_call(call_id)
        print(f"status: {call.get('status')}")

    out_dir = Path("data/probe")
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"probe-{stamp}.json"
    dest.write_text(json.dumps(call, indent=2))

    print(f"terminal status: {call.get('status')}")
    print(f"top-level payload keys: {sorted(call.keys())}")
    print(f"full payload saved to {dest} (gitignored; scrub before any fixture use)")
    service.close()


if __name__ == "__main__":
    asyncio.run(main())
