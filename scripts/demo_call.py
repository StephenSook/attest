"""Consented third-party demo call. Operator-run only; never invoked by tests or CI.

Unlike probe_call.py and study_call.py, which dial the operator's own line, this
places ONE real call to a third party who has given written consent. It exists as
a script rather than a curl so the call is reproducible and auditable after the
fact, and so the disclosure text cannot be typed differently on the night.

Three properties that matter:

1. The task comes from ``app.runs.build_task``. It is NOT written here. That is the
   same disclosure-first script the product builds server-side, carrying the AI
   identity, the voicemail rule, and the refusal to invent patient details. A demo
   that used a hand-written task would be demonstrating something we do not ship.
2. The full terminal payload is written to disk the moment it arrives. Production
   runs on an ephemeral free-tier database that reseeds on restart, and a consented
   call to someone else's line cannot be placed twice, so the durable capture
   happens here rather than in a service that may restart.
3. Nothing is scrubbed here. Scrubbing is a separate, reviewable step, because a
   script that both fetches and redacts can silently destroy the only copy of the
   evidence if its redaction is wrong.

    set -a && source .env && set +a
    uv run python scripts/demo_call.py --phone +15550101234 --org "Example Practice" \
        --label tara --dry-run
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from app import runs
from app.calle import CalleService

PROD_BASE_URL = "https://api.heycall-e.com"
POLL_SECONDS = 5.0
TIMEOUT_SECONDS = 600.0
TERMINAL = {"completed", "failed", "canceled"}
OUT_DIR = Path(__file__).parent.parent / "data" / "demo"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone", required=True, help="+1E.164 recipient")
    parser.add_argument("--org", required=True, help="organization name, exactly as published")
    parser.add_argument("--plan", default=None, help="plan name to verify, omit if none is claimed")
    parser.add_argument("--label", required=True, help="short label for the saved payload")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the exact task and recipient, then exit without dialing",
    )
    args = parser.parse_args()

    import os

    api_key = os.environ.get("CALLE_API_KEY", "")
    if not api_key:
        sys.exit("Set CALLE_API_KEY in the environment first.")

    claims: dict[str, str] = {}
    if args.plan:
        claims["plan_name"] = args.plan
    task = runs.build_task(args.org, claims)

    print("=" * 72)
    print("RECIPIENT:", args.phone)
    print("ORG:", args.org)
    print("CLAIMS:", claims or "{office name, accepting new patients}")
    print("=" * 72)
    print(task)
    print("=" * 72)

    if args.dry_run:
        print("DRY RUN: nothing was dialed.")
        return

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    service = CalleService(api_key=api_key, base_url=PROD_BASE_URL)
    created = await service.place_call(
        task=task,
        phone=args.phone,
        idempotency_key=f"attest-demo-{args.label}-{stamp}",
        metadata={"purpose": "demo", "budget_line": "demo_takes", "label": args.label},
    )
    call_id = str(created.get("id", ""))
    print(f"created: id={call_id} status={created.get('status')}")

    call = created
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline and call.get("status") not in TERMINAL:
        await asyncio.sleep(POLL_SECONDS)
        call = await service.get_call(call_id)
        print(f"status: {call.get('status')}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / f"demo-{args.label}-{stamp}.json"
    dest.write_text(json.dumps(call, indent=2))
    print(f"\nRAW payload saved to {dest}")
    print("  gitignored. Scrub phone AND any identifying names before any fixture or commit.")

    if call.get("status") not in TERMINAL:
        service.close()
        sys.exit(f"timed out before terminal; last status {call.get('status')}")

    print(f"terminal status: {call.get('status')}")
    service.close()


if __name__ == "__main__":
    asyncio.run(main())
