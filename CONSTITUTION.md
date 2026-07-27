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

No auth/multi-tenancy (one judge-gated credential only). No batch-calling UI. No inbound, phone trees, transfers, DTMF, or mid-call tool use (platform cannot). No compliance dashboard, no own MCP server, no scheduler.

AMENDED 2026-07-27: the no-mobile-app line was lifted deliberately once the
web loop was complete and deployed. Attest Pocket (`mobile/`) ships as a
read-only companion on iOS and Android. Nothing else in the out-of-scope
list has been lifted. No second vertical. No CRM/EHR integrations. The cinematic landing has a hard floor (static hero + one scroll chapter) it can collapse to on the Sep 3 trigger.

## Gates

| Gate | Date | Condition |
| --- | --- | --- |
| G0 | Jul 31 | KYC cleared, one real call placed, fixture committed, validator conversation booked |
| G1 | Aug 10 | Full loop e2e vs mock; kill-and-restart resumes; one real webhook delivery verified |
| G2 | Aug 21 | One artifact produces a real figure from held-out data; eval command clean |
| G3 | **Sep 11** | Skill pull request opened upstream (deliberately late; see below) |
| G4 | Sep 7 | Feature freeze; demo-consent decision locks |
| G5 | Sep 12 | Everything submitted, two days early |

Slips trigger the descope ladder in BUILD_PLAN.md (in the planning workspace), never a slide.

### Why G3 moved from Aug 31 to Sep 11 (amended 2026-07-27)

G3 previously said Aug 31 while a separate standing instruction said hold until Sep 8. Two
locked dates contradicting each other is worse than either one, so this is the deliberate
amendment rather than a discovery at the gate.

The rule, read from the source rather than from our notes. The Devpost submission form field
`Project submission pull request URL` (id 27833) is `required: true`, and the host's instruction
is to **open** a pull request and provide the URL. Nothing anywhere requires it to be **merged**.
Submissions close 2026-09-14 15:45 UTC. Judging runs Sep 30 to Oct 13.

So the only hard constraint is that the PR exists and has a URL when we submit at G5 on Sep 12.

Opening it earlier buys nothing and costs something real: the skill is the one artifact that
reveals the verification pattern, the repository is public, and every day it sits open before
the deadline is a day a competitor can read it and copy the approach. Opening Aug 15 would have
given rivals a month. Sep 11 gives them three days, which is not enough to rebuild a calibrated
abstention system, and it still leaves us a three-day margin to the Sep 14 deadline if the
upstream validator has changed again or a maintainer asks for edits.

There is also an upside to the timing that is worth naming. Community pull requests there have
been merging within days, so a PR opened Sep 11 will most likely be merged during the Sep 14 to
Sep 30 gap. Judges opening it during judging see a merged contribution; rivals racing the
deadline saw it for three days. Do not chase a merge before submission: merged pull requests get
announced in their Discord, which is additional exposure we do not need on Sep 12.

Standing rule: never open it earlier than this without Stephen saying so explicitly, and
re-run the upstream validator against a fresh clone of upstream HEAD immediately before opening,
because that validator has already changed under us once.
