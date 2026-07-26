"""Real-channel study dialer. Operator-run only; never invoked by tests or CI.

Places the manifest's calls one at a time to the operator's own consented
line (ATTEST_PROBE_PHONE), polls each to terminal, scrubs the phone number,
and saves the payload beside the manifest. The respondent answers from the
printed sheet for that call number, so ground truth is known at dial time.

    set -a && source .env && set +a
    uv run python scripts/study_call.py --from 1 --to 12
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from app import runs
from app.calle import CalleService

PROD_BASE_URL = "https://api.heycall-e.com"
POLL_SECONDS = 5.0
TIMEOUT_SECONDS = 480.0
GAP_SECONDS = 15.0
TERMINAL = {"completed", "failed", "canceled"}

DATA_DIR = Path(__file__).parent.parent / "eval" / "study_data"
CALLS_DIR = DATA_DIR / "calls"


def _scrub(obj: object, phone: str) -> object:
    if isinstance(obj, dict):
        return {k: _scrub(v, phone) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v, phone) for v in obj]
    if isinstance(obj, str):
        return obj.replace(phone, "+15550101234")
    return obj


async def _one_call(service: CalleService, phone: str, n: int, seed: int) -> dict[str, object]:
    task = runs.build_task("Attest builder test line", {})
    created = await service.place_call(
        task=task,
        phone=phone,
        idempotency_key=f"attest-study-{seed}-{n:02d}",
        metadata={"purpose": "real-channel-study", "budget_line": "real-call validation", "n": n},
    )
    call_id = str(created.get("id", ""))
    if not call_id:
        raise RuntimeError(f"call {n}: provider returned no id")
    print(f"call {n}: created {call_id}")
    call: dict[str, object] = created
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline and call.get("status") not in TERMINAL:
        await asyncio.sleep(POLL_SECONDS)
        call = await service.get_call(call_id)
    if call.get("status") not in TERMINAL:
        raise RuntimeError(f"call {n}: timed out at status {call.get('status')}")
    return call


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=int, required=True)
    parser.add_argument("--to", dest="end", type=int, required=True)
    args = parser.parse_args()

    phone = os.environ.get("ATTEST_PROBE_PHONE", "")
    api_key = os.environ.get("CALLE_API_KEY", "")
    if not phone or not api_key:
        sys.exit("Set CALLE_API_KEY and ATTEST_PROBE_PHONE in the environment first.")

    manifest_path = DATA_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    CALLS_DIR.mkdir(parents=True, exist_ok=True)
    service = CalleService(api_key=api_key, base_url=PROD_BASE_URL)
    try:
        for call_row in manifest["calls"]:
            n = int(call_row["n"])
            if n < args.start or n > args.end:
                continue
            if call_row["status"] == "done":
                print(f"call {n}: already collected; skipping")
                continue
            print(
                f"\ncall {n} of {manifest['n']} [{call_row['persona']}]\n"
                f'  SAY: "{call_row["line"]}"\n'
                f"  (go by THIS line, not the paper sheet)",
                flush=True,
            )
            payload = await _one_call(service, phone, n, int(manifest["seed"]))
            scrubbed = _scrub(payload, phone)
            dest = CALLS_DIR / f"call_{n:02d}.json"
            dest.write_text(json.dumps(scrubbed, indent=2) + "\n")
            raw = dest.read_text()
            if phone in raw:
                dest.unlink()
                raise RuntimeError(f"call {n}: real phone survived scrub; payload discarded")
            call_row["status"] = "done"
            call_row["calle_call_id"] = str(payload.get("id", ""))
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            print(f"call {n}: saved ({payload.get('status')})")
            if n < args.end:
                await asyncio.sleep(GAP_SECONDS)
    finally:
        service.close()
    print("\nsession slice complete; run `uv run python -m eval.study analyze` after all sessions")


if __name__ == "__main__":
    asyncio.run(main())
