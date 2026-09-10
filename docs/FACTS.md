# Attest fact sheet

The single source every judge-facing artifact draws from: the README, the
Devpost submission, and the demo video narration all cite THIS file, and this
file cites the shipped code. Every entry lists where it was verified. If an
artifact needs a number that is not here, add it here first, with its audit.

Last audited: 2026-09-09, full pass against shipped code and live surfaces.

Audit method, because "audited" has to mean something: every number below was re-read from its
generating artifact (`eval/results/metrics.json`, `eval/results/real_channel.json`,
`eval/results/ablation.md`), every physical asset was re-measured with ffprobe, every deployed
surface was fetched, and every code claim was grepped in the shipped source. Nothing was confirmed
from the README, from a prior version of this file, or from memory. That pass corrected stale
figures and wording that had drifted from the shipped code.

## Product claims

| Claim | Verified against |
| --- | --- |
| CALL-E is imported and called at runtime via the official Python SDK | `backend/app/calle/client.py:13` (`from calle import CalleClient`); real calls placed through this seam on 2026-07-25 |
| Every returned yes/no answer carries a verbatim span with character offsets; abstentions may have no span | `backend/app/extract.py` (`ExtractionResult.span_char_start/end`); enforced in `tests/test_artifact_two.py` |
| Hedge detection uses a graded lexicon that dampens trust proportionally | `backend/app/hedge.py` |
| Reconciliation is direct Fellegi-Sunter with fixed documented priors | `backend/app/reconcile.py` (`_FIELD_PARAMS`, `PRIOR_LOG_ODDS`) |
| The conformal core is implemented directly and finite-sample corrected; its marginal coverage guarantee assumes exchangeability with the seeded scenario distribution | `eval/conformal.py` (`conformal_quantile`); `eval/personas.py` defines the seeded distribution |
| Do NOT claim: MAPIE, Splink, shadcn/ui, numpy | struck 2026-07-25; never imported anywhere (`grep -ri mapie\|splink` returns nothing in code) |

## Problem statistics (sourced; quote only these)

- A CMS review of Medicare Advantage online provider directories found inaccuracies in 45 to 52 percent of listings across three audit rounds (CMS Online Provider Directory Review Industry Report, final round 2018: 48.74 percent of locations had at least one inaccuracy).
- A 2023 secret-shopper study of Medicaid managed-care mental-health directories ("ghost networks", Senate Finance Committee majority staff report, May 2023) reached a bookable appointment in 18 percent of attempted calls.
- Simon F. Haeder and Jane M. Zhu (Health Affairs Scholar, 2024, DOI 10.1093/haschl/qxae079) re-contacted physician listings and found 44.8 percent still contained at least one error, while 11.6 percent were accurate on all audited dimensions.
- Framing rule: these are directory-accuracy statistics, not claims about any specific insurer or practice. Cite the study, never a named organization.

## Evaluation numbers (canonical: `eval/results/metrics.json`, seed 20260725)

| Number | Value |
| --- | --- |
| Scenario folds | 300 calibration / 300 held-out test, disjoint |
| Personas | cooperative, hedging, contradictory, evasive, wrong_number, refuses |
| Empirical coverage at 90% target | 90.3% (Wilson 95%: 86.5 to 93.2) |
| Abstention rate | 57.7% |
| Accuracy when answering | 96.9% |
| Error when forced to answer everything | 12.3% |
| Ablation: no hedge detection | accuracy-when-answering drops to 87.8% (abstention 42.7%) |
| Ablation: no dead-end guard | accuracy-when-answering drops to 89.8%; abstention falls to 54.3% |
| Ablation: no calibration | 89.1% accuracy, abstention collapses to 11.7%, no coverage guarantee at all |

Read the ablation abstention numbers against the full config's **57.7%**, not against zero: every
ablation abstains LESS than the shipped system, which is the point. Removing a guard does not make
the system more cautious, it makes it answer more often and be wrong more often. Canonical table:
`eval/results/ablation.md`.

Regeneration: `uv run python -m eval` reproduces the seeded metrics and figures on a clean checkout. `uv run python -m eval.study analyze` separately reproduces `real_channel.json`. Do not quote any eval number from memory; re-read the generated artifacts.

## Real-channel transfer study (final, audited 2026-07-27)

- 36 pre-registered scripted calls placed to the consented builder line across three sessions (2026-07-26 to 27); the respondent answered from ground-truth script sheets. 8 calls excluded by the documented deviation protocol (sheet-drift attribution ambiguity on hedged lines), leaving n=28.
- At the HARNESS-calibrated threshold (qhat 0.75, never fit on this data): empirical coverage 100.0% (28 of 28; 95 percent Wilson lower bound 87.9%), abstention 42.9%, accuracy when answering 100.0%.
- Reading, stated precisely: on the 28 attributable calls, coverage was 28 of 28 and every answered call was correct. Measured against the SAME gate, the real channel abstained LESS than the seeded harness, 42.9 percent against 57.7 percent, and still produced no wrong answers. This is a transfer test of extraction plus calibration across the real channel (does the system faithfully report or abstain on what was actually said), not a claim about underlying directory facts.
- Selection-bias floor: the 8 excluded calls are non-random (ambiguous hedged deliveries). Counting every excluded call as a coverage miss gives a worst-case floor of 77.8 percent; 6 of the 8 abstained, and counting the 2 that answered as errors gives a worst-case accuracy-when-answering of 88.9 percent. Both bounds ship in the report.
- Provenance on every surface: real phone channel, builder-answered scripted ground truth, consented builder line, never presented as calls to real practices. Reproduce this analysis with `uv run python -m eval.study analyze`.

## Class-conditional (Mondrian) findings (audited 2026-07-26)

- The marginal 90.3 percent coverage HID a per-class gap on the held-out fold: "no" answers were covered 83.2%, below the 90 percent target, while "unknown" sat at 100%. Class-conditional thresholds (one finite-sample-corrected quantile per true class) lift "no" to 88.5% and "yes" to 92.2%; overall Mondrian coverage 93.0%.
- Calibration-size sensitivity: coverage stays between 90.3 and 93.0 percent as the calibration fold shrinks from 300 to 50, so the guarantee is not an artifact of a large calibration set. Figure: eval/results/calibration_sensitivity.svg.
- Both hand-rolled in eval/conformal.py, seeded, and regenerated by `uv run python -m eval`. Headline metrics unchanged.

## Real-call facts (audited 2026-09-09)

- Two probe calls and one webhook-delivery test call placed through the seam to the builder's own phone with consent, plus one post-KYC canary to CALL-E's published testing hotline. First probe: no spoken response; the system reported `task_completed: false` rather than inventing an answer. Second probe: answered; `task_completed: true`, platform confidence 0.92.
- The scrubbed second-probe payload is the mock fixture (`mock_calle/fixtures/terminal_result.json`): phone and identifiers replaced with reserved fictional values, conversation verbatim.
- Platform findings, all verified empirically: the live API rejects both `result_schema` and `recipient_result_schema`; `webhook_url` was accepted but no webhook was delivered for a completed call (tunnel capture, 20+ minutes; time-scoped finding, see below); terminal payloads are snake_case `call_task` objects with `recipients[].attempts[].transcript_turns`, `completion_confidence`, and `evidence`; and, **as of 2026-07-27, no KYC gate stood between an
account and an outbound call**, established by placing 40 real calls rather than by reading docs.

**The webhook finding is time-scoped and the platform has since moved twice.** The changelog dated
2026-07-29 ("Terminal webhook delivery") states call tasks with `webhook_url` "now send terminal
event notifications", retried on non-2xx, deduplicated by a `CALL-E-Event-Id` header. Those
deliveries are UNSIGNED: no webhook secret, no `CALL-E-Timestamp`, no `CALL-E-Signature`, and SDK
0.6.0 deprecates its `verify`/`unwrap` helpers ("current CALL-E webhooks are unsigned"). The docs
recommend re-fetching `GET /v1/calls/{call_id}` before any sensitive side effect, which is the
poller-authoritative design this repo shipped from the start. Verified 2026-08-05 by reading
docs.heycall-e.com/changelog.md, webhooks.md, and the calle-ai 0.6.0 wheel from PyPI.

**Delivery MEASURED 2026-08-05, same day:** one canary call to CALL-E's own published inbound
testing hotline (budget line webhook-live-test, `--hotline` on scripts/probe_call.py) went terminal
`failed` (the hotline's test agent hung up during the greeting: `DECLINED (Hangup by: user)`), and
about a minute later the platform POSTed the terminal event to our deployed receiver, which
accepted it 202 in hint mode (Render request log 17:16:58Z, source 47.237.20.72, an Alibaba Cloud
address consistent with their infrastructure). So terminal webhook delivery is real, measured on
our own receiver, including for failed calls. The same canary also established that outbound
dialing still works after the platform's v0.6.0 changes with no KYC gate enforced on this account,
and that terminal payloads now carry a top-level `structured_result` key.

**The account state changed after the build window and was re-verified end to end.** On 2026-09-09
the account holder completed Persona identity verification. A fresh dashboard load then showed the
account verified, the purchased US number available for both inbound and outbound calls, and that
number persisted as the default outbound line. A fresh canary through `scripts/probe_call.py` to
CALL-E's published testing hotline completed at 18:04:33Z with `task_completed: true`, confidence
0.90 (high), and no failure. This establishes the state of this account and seam at that time; it
is not a claim that every CALL-E account follows the same approval path.

**Operational response:** the public judge sandbox still defaults closed and production keeps
`ATTEST_SANDBOX_ENABLED=0`. Identity verification removed the provider-side blocker, but the
sandbox still relies on a caller's consent attestation rather than proving destination ownership,
and the deployed database is ephemeral. The live run page reports that state before collecting a
number. Retained real-call evidence, replay, certificate verifier, mobile builds, and the
zero-credential Docker path remain judge-accessible without placing a new call.

## Judge sandbox facts (audited 2026-07-27)

- If an operator explicitly enables it, the judge key lets a judge request a call to a number for which they attest consent. The system does not prove ownership. Rails, all fail-closed and test-pinned: explicit StrictBool consent (422 without it); one call per phone-number hash within the current database lifetime; a cap of 15 within that database lifetime; +1 NANP-format numbers only; a limited area-code filter for 900, 976, and 950; and kill switch ATTEST_SANDBOX_ENABLED=0 (503). Dedup and cap are enforced in one serialized SQLite transaction, so concurrent requests cannot bypass either rail across workers. The area-code filter is not a complete tariff or destination-country classifier, which is another reason production keeps the sandbox closed.
- A second-model adversarial pass (Codex) found both rails were originally raceable and that consent is not proof of ownership; the races are fixed atomically. Accepted residual, stated plainly: within one persistent database lifetime, a holder of the secret judge key could cause up to 15 disclosed calls to numbers they do not own. The deployed database is ephemeral, so those lifetime limits reset after a redeploy. Full ownership proof needs a separate verification provider we do not run. Production therefore keeps the sandbox disabled.
- Before CALL-E receives a request, Attest persists only a keyed HMAC-SHA256 digest binding the exact task, destination, webhook, provider mode, endpoint, and API credential, plus an attempt count, ten-minute cutoff, and owner-token lease. It does not persist the raw destination for recovery. If a response is lost, an identical client request may reuse the original idempotency key after the lease ends. A changed request, credential rotation, provider switch, concurrent attempt, or late retry fails closed. After any ambiguous first attempt, a later 4xx cannot release the sandbox reservation because it does not prove the original call was rejected.
- The operator key path is unrestricted and never railed; the two keys are distinct env vars.

## Mobile facts (audited 2026-07-27)

- Attest Pocket: Expo SDK 57 app in mobile/, read-only against the production API, no secrets in the binary, phone numbers masked server-side. Runs ledger, run detail (verdict stamp, claim cards, span-marked transcript synced to an expo-audio player of the receiving-end recording), PDF attestation certificate via the native share sheet, calibration screen with the real-telephone panel.
- Android: APK built on EAS with zero Apple involvement, hosted permanently as the GitHub release pocket-v0.1.0 asset (Expo artifact links expire in about 30 days and would die mid-judging). QR committed at docs/mobile/android-apk-qr.png.
- iOS: ad-hoc build installed on the builder's registered iPhone; store build 1.0.0 (3) APPROVED by Apple Beta App Review 2026-07-27 (verified against the App Store Connect API: betaReviewState APPROVED, processingState VALID), assigned to external group "Public Testers". The public link was enabled 2026-07-27 and is live at <https://testflight.apple.com/join/XZDXt7jw>, open to anyone with no tester limit. Verified two ways rather than from a screenshot: the API reports publicLinkEnabled true and returns that exact publicLink, and an unauthenticated fetch of the URL returns HTTP 200 with the title "Join the Attest Pocket beta". QR committed at docs/mobile/testflight-qr.png. Standing rule that produced this: never claim the public link exists until the API returns one, because approval and a link are different switches.
- Watcher: a read-scoped ASC API key (attest-review-watch, .p8 in gitignored .secrets/) feeds a poller that checks betaReviewState every 30 minutes.

## Deployment facts

- Frontend: https://attest-web-phi.vercel.app (Vercel project `attest-web`). Note: `attest-web.vercel.app` (no suffix) is an unrelated third-party product.
- Backend: https://attest-api-o5gm.onrender.com (Render free tier, service `attest-api`, seeded on boot, database ephemeral by design).
- Keepalive: GitHub Actions cron at offset minutes `4,14,24,34,44,54`; verify by newest-run age, not green runs.
- Zero-credential judge path: `docker compose up --build` (api + mock + console; live dialing off).
- Live-call gate: `POST /internal/runs` requires the `X-Attest-Key` header; 403 on mismatch, 503 when unconfigured. Public API redacts every phone number (test-enforced).

## Audio evidence facts (audited 2026-07-26)

- The CALL-E Calls API and Python SDK expose no recording URL: verified field-by-field on the real terminal payload and by grepping the installed SDK. The dashboard may expose recordings through its own authenticated interface. Logged as feedback to the platform.
- Run audio therefore only exists when captured on our own end of a consented call and placed in ATTEST_AUDIO_DIR. The console's waveform player renders only when audio exists, always with a provenance label, and clicking an evidence span seeks playback to that turn.
- CI exercises the player with a synthetic alignment tone labeled "synthetic alignment tone, CI harness only" (ATTEST_SEED_TEST_TONE=1, set nowhere in production).
- Real audio shipped 2026-07-26: a consented builder-line call recorded on the receiving end by the builder, trimmed and loudness-normalized (25.6s, -17 LUFS integrated, mono AAC), scrubbed payload seeded as run_replay_builder_0001 with the label "audio captured on the receiving end of this consented call, builder line". Its verdict is honestly unverifiable at posterior 0.72: one agreeing field is +1.36 bits from an even prior, below the 0.85 verified bar. The extraction span is "Yes. We're we're accepting new patients." with real crosstalk earlier in the call.

## Landing film provenance (audited 2026-07-25)

- Hero film: Higgsfield Cinema Studio v2 (pro mode, 16:9, linear speedramp, sound off), prompt: single continuous extreme-macro journey from a telephone handset grille along copper wire to a nib writing in blue ink, ending on a brass notary seal. 12 credits.
- Post: ffmpeg minterpolate (mci) 24 to 60fps, h264 crf 22, keyframe every 8 frames, audio stripped. Measured shipped file: 7.97s, 1920x1080, 478 frames, 61 keyframes, 8.7MB, zero audio streams.
- Scrub safety is test-enforced: tests/test_film_asset.py parses the mp4 sync-sample table and fails if keyframes are sparser than one per half second; e2e drives a wheel stream to document end.

## Engineering facts

- Strict mypy; ruff lint + format in CI; gitleaks over full history in CI. Test counts change on
  every merge, so they are recorded here as a dated snapshot and must be re-read before being quoted
  anywhere: **359 backend tests collected and 6 mobile tests, as of 2026-09-09**. Regenerate with
  `uv run pytest --collect-only -q | tail -1`,
  `cd mobile && node --experimental-strip-types --test "src/**/*.test.ts"` (the mobile count comes
  from the node test runner, not jest: an ad-hoc `npx jest` reports 0 because it is not the runner
  CI uses). Deliberately not repeated in the
  README, because a count duplicated across surfaces is a count that goes stale on one of them: that
  drift has now been caught four separate times on this repository, most recently when the upstream
  review wave took the backend suite from 221 to 243 while the Devpost writeup still said 221.
- The upstream skill `skills/verify-by-phone` passes `validate_repository.py` from CALLE-AI/awesome-phone-call-agents staged against a clean clone. **Upstream PR [#39](https://github.com/CALLE-AI/awesome-phone-call-agents/pull/39) was MERGED on 2026-08-07** (merge commit `87ca859`, 9 commits, 15 files), after five maintainer review rounds; `skills/verify-by-phone` is on that repository's `main` and can be read there rather than taken on our word. The submission requirement is only to open a pull request and provide the URL, so this is that requirement met in its strongest form, not a change of state that affects eligibility. Re-validated on every change to the skill, most recently 2026-08-07, because the validator itself changes upstream (it gained a CRLF fix after our first pass).
- A maintainer review of PR #39 on 2026-07-29 found seven blockers, all real, all fixed: the abstention gate could answer when the calibrated set was `{unknown}`; a later answer was credited to an earlier question, span-grounded to the wrong sentence; reconciliation never passed `--qhat` and so could only print UNVERIFIABLE; the idempotency key was random and printed only after success; nothing established that the respondent represented the listing; the quick start died on Python 3.9 at import; and the saved payload was world-readable. No reported number moved: `metrics.json` and `real_channel.json` regenerate byte-identical after all seven. Both worked examples in the skill are now diffed against real command output in CI, because one of the seven was a documented figure that contradicted the program.
- Four further review rounds followed the first seven, ending in the merge. Round 2 (5 blockers, 2026-07-29): identity was fail-open, absence of a denial is not confirmation; both claim questions in one bot turn put a single "Yes." on both claims; a transcript-less call exited non-zero instead of abstaining; a claimless run dialed anyway; and the Python floor was misstated. Round 3 (2): a negated organization name confirmed instead of denying. Round 4 (1): the negation check was position-dependent, so "Example Family Medicine? No, this is Buckhead Clinic" attributed the call to the wrong practice. Round 5 (1, 2026-08-06): a comma was telling a front-desk greeting apart from a question, so "Example Family Medicine, right?" confirmed the listing. Identity is now bound to the speech act: only an unambiguous self-identification, or an affirmative answering an identity question the agent actually asked, establishes it. Every round's finding is fixed and covered by a committed regression test, and no reported number moved in any round.
- Before shipping the round-5 fix we attacked it ourselves: a second-model pass found 3 defects in it (one an inversion, where a greeting outvoted an explicit denial in the same turn), and a five-lens adversarial sweep of 35 agents found **17 more verified breaks** (13 further candidates were refuted and dropped). The sharpest: the maintainer's own rejected sentence with the question mark deleted still confirmed, because punctuation is a transcription artifact and the respondent does not control it. Also caught: the name used as a destination or a subject ("transfer you to X", "X is upstairs"), a repudiation one clause away from the name, one distinctive word standing in for a whole name ("New Life Health Center" reduces to {new, life}, so "not accepting new patients" both matched the name and negated it), a bare "No." to the agent's own identity question never denying, and two defects predating the round entirely, one of which flipped verdicts in BOTH extractors on a single typographic apostrophe.
- Second-model adversarial review found 7 verified issues in the loop/security wave (all fixed and regression-pinned); the harness twice caught confident-wrong extraction ("there's NO doctor's office here" parsing as a no; a plan claim stealing an unrelated span).
- Lighthouse, measured 2026-08-05 against the deployed landing (mobile emulation, lighthouse latest via npx): **performance 81, accessibility 100, best practices 100, SEO 100**; CLS 0, TBT 80ms, FCP 3.3s, LCP 3.8s under mobile throttling. The FCP cost is the cinematic landing's script weight and is a deliberate trade: per-route code splitting already ships, and the scroll engine is not being refactored for a Lighthouse point because a traversal regression on the judge-facing landing outweighs one (the scroll-scrub freeze was exactly that class of bug). Mobile-viewport traversal and horizontal-overflow assertions are pinned in frontend/e2e/console.spec.ts. Do not claim "performance 90+" anywhere; 81 is the measured number.

## Saying this out loud (the plain-language version)

Written because a domain expert who has run this exact kind of study could not follow the
explanation twice in one conversation, and asked to hear it "in general terms, not computer
science terms". If it cannot be said to him it cannot be said to a judge either. The demo
narration and any live pitch use this version. Every number in it is the same number as above,
just spoken.

**Banned from spoken copy:** threshold, calibration, calibrated, coverage, conformal, quantile,
prediction set, alpha, posterior, marginal. Each one has a plain replacement below.

### One sentence

Attest makes one phone call to a doctor's office to check whether what your insurance directory
says about them is actually true, and when the call does not give a clear answer it says so
instead of guessing.

### Sixty seconds (measured: 165 words, so 62 to 71 seconds depending on pace)

Re-count the words if you edit it. The first draft of this was labelled sixty seconds and ran
eighty-nine, which is the same class of unchecked claim the rest of this file exists to prevent.

Half the listings in health insurance directories are wrong. You call the number and it is a nail
salon. Nobody finds out until a patient needs care.

Attest makes the call. It says up front that it is an automated assistant and why it is calling,
asks what a patient would ask, and records the answer with the exact words the person said.

What matters is what it does when the call is unclear. Somebody hedges, or it is voicemail. Most
systems hand you an answer anyway. This one refuses.

We tuned how cautious it needs to be on three hundred scripted synthetic transcript scenarios
where we knew the truth, then ran it on three hundred held-out scenarios it had never seen. The true answer was in what it reported at least nine times
in ten. It stayed quiet a little over half the time. When it answered, it was right about
ninety-seven times in a hundred.

That last number only counts because of the silence in front of it.

### Translation table, for anyone editing the script

| Do not say | Say |
| --- | --- |
| calibrated confidence | how cautious it needs to be, tuned on scripted synthetic transcript scenarios where we knew the truth |
| empirical coverage 90.3 percent | the true answer was in what it reported at least nine times out of ten |
| abstention rate 57.7 percent | it stayed quiet a little over half the time |
| accuracy when answering 96.9 percent | when it did answer, it was right about ninety-seven times in a hundred |
| held-out test fold | three hundred different scripted synthetic transcript scenarios it had never seen |
| the model abstains | it refuses to answer |
| verbatim span with character offsets | the exact words the person said, so you can check it |

## Language rules for every artifact

- The eval dataset is scripted seeded scenario data and is labeled as such wherever it appears; real calls are the only thing presented as real calls.
- No em-dashes; no AI-marketing vocabulary; numbers always from this sheet's sources, never from memory.
