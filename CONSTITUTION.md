# Attest Constitution

Definition of done, demo flow, and the budgets this project is governed by. When a decision conflicts with this file, this file wins or gets amended deliberately.

## Definition of done, per component

- **Integration:** a real call completes end to end and the structured result validates against the Pydantic model. Validation is our own post-call layer: the live API rejects result_schema at call creation (verified 2026-07-25), so schema enforcement upstream is blocked on the platform, not on us.
- **State machine:** killing the process mid-call and restarting resumes correctly from SQLite.
- **Webhook:** signature verified over raw bytes, replayed delivery is a no-op, SSRF blocklist unit-tested against loopback, private, and metadata addresses.
- **Artifacts:** each produces a figure a reviewer understands in under ten seconds, generated from held-out data.
- **Eval:** one command (`uv run python -m eval`) reproduces every README number on a clean checkout.
- **Skill:** installs and runs on a machine that has never seen this repository.

## Demo flow (the three-minute video spine)

1. The problem in the first ten seconds: ghost networks, roughly half of directory listings wrong.
2. A real call placed and completing before the thirty-second mark, disclosure heard on tape.
3. The structured result, each field lighting up its verbatim transcript span.
4. The reconciliation verdict against the directory record.
5. An abstention, with its coverage number, on a call where the answer was hedged.
6. The reliability diagram and risk-coverage curve, regenerated live from the eval command.

## Call budget

Pricing intel (CALL-E Discord, PM statements, 2026-07-25): $0.05 per billable call, so the
current $6.00 balance is roughly 120 calls. No-answer and failed routes are free; voicemail
and low-confidence results charge the call fee only. The table below stays deliberately
conservative; every real call still gets logged, and no automated test ever dials.

| Purpose | Calls | Notes |
| --- | --- | --- |
| First probe + fixture capture | 3 | Terminal payload committed as scrubbed fixture |
| Real webhook delivery test | 2 | Week 2, via tunnel or early deploy |
| Reliability-layer validation on real calls | 6 | Spot-validates the harness-computed guarantee |
| Demo takes | 6 | Final video only |
| Reserve | 3 | Unplanned retakes or debugging |

Every real call gets logged in `docs/call-log.md` against this table. No automated test ever dials a real number.

## Out of scope (the firewall)

No auth/multi-tenancy (one judge-gated credential only). No batch-calling UI. No inbound, phone trees, transfers, DTMF, or mid-call tool use (platform cannot). No compliance dashboard. No mobile app, no own MCP server, no scheduler. No second vertical. No CRM/EHR integrations. The cinematic landing has a hard floor (static hero + one scroll chapter) it can collapse to on the Sep 3 trigger.

## Gates

| Gate | Date | Condition |
| --- | --- | --- |
| G0 | Jul 31 | KYC cleared, one real call placed, fixture committed, validator conversation booked |
| G1 | Aug 10 | Full loop e2e vs mock; kill-and-restart resumes; one real webhook delivery verified |
| G2 | Aug 21 | One artifact produces a real figure from held-out data; eval command clean |
| G3 | Aug 31 | Skill pull request opened upstream |
| G4 | Sep 7 | Feature freeze; demo-consent decision locks |
| G5 | Sep 12 | Everything submitted, two days early |

Slips trigger the descope ladder in BUILD_PLAN.md (in the planning workspace), never a slide.
