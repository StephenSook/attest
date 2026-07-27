# Attest fact sheet

The single source every judge-facing artifact draws from: the README, the
Devpost submission, and the demo video narration all cite THIS file, and this
file cites the shipped code. Every entry lists where it was verified. If an
artifact needs a number that is not here, add it here first, with its audit.

Last audited: 2026-07-27.

## Product claims

| Claim | Verified against |
| --- | --- |
| CALL-E is imported and called at runtime via the official Python SDK | `backend/app/calle/client.py:13` (`from calle import CalleClient`); real calls placed through this seam on 2026-07-25 |
| Every extracted answer carries a verbatim span with character offsets, or abstains | `backend/app/extract.py` (`ExtractionResult.span_char_start/end`); enforced in `tests/test_artifact_two.py` |
| Hedge detection uses a graded lexicon that dampens trust proportionally | `backend/app/hedge.py` |
| Reconciliation is direct Fellegi-Sunter with fixed documented priors | `backend/app/reconcile.py` (`_FIELD_PARAMS`, `PRIOR_LOG_ODDS`) |
| The conformal core is implemented directly, finite-sample corrected | `eval/conformal.py` (`conformal_quantile`) |
| Do NOT claim: MAPIE, Splink, shadcn/ui, numpy | struck 2026-07-25; never imported anywhere (`grep -ri mapie\|splink` returns nothing in code) |

## Problem statistics (sourced; quote only these)

- A CMS review of Medicare Advantage online provider directories found inaccuracies in 45 to 52 percent of listings across three audit rounds (CMS Online Provider Directory Review Industry Report, final round 2018: 48.74 percent of locations had at least one inaccuracy).
- A 2023 secret-shopper study of Medicaid managed-care mental-health directories ("ghost networks", Senate Finance Committee majority staff report, May 2023) reached a bookable appointment in 18 percent of attempted calls.
- Zhu, Zhang, and Polsky (Health Affairs Scholar, 2024) re-called physician listings and found 44.8 percent of entries still contained at least one error, and only 11.6 percent of listings were accurate on all audited dimensions.
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
| Ablation: no hedge detection | accuracy-when-answering drops to 89.1% |
| Ablation: no dead-end guard | abstention doubles to 54.3%, accuracy still worse (89.8%) |
| Ablation: no calibration | 89.1% accuracy, no coverage guarantee at all |

Regeneration: `uv run python -m eval` reproduces every number and figure above on a clean checkout. Do not quote any eval number from memory; re-read `metrics.json`.

## Real-channel transfer study (final, audited 2026-07-27)

- 36 pre-registered scripted calls placed to the consented builder line across three sessions (2026-07-26 to 27); the respondent answered from ground-truth script sheets. 8 calls excluded by the documented deviation protocol (sheet-drift attribution ambiguity on hedged lines), leaving n=28.
- At the HARNESS-calibrated threshold (qhat 0.75, never fit on this data): empirical coverage 100.0% (28 of 28; 95 percent Wilson lower bound 87.9%), abstention 42.9%, accuracy when answering 100.0%.
- Reading, stated precisely: on the 28 attributable calls, coverage was 28 of 28 and every answered call was correct; channel noise became honest abstention (42.9 percent vs 26.7 on the harness), the designed failure mode. This is a transfer test of extraction plus calibration across the real channel (does the system faithfully report or abstain on what was actually said), not a claim about underlying directory facts.
- Selection-bias floor: the 8 excluded calls are non-random (ambiguous hedged deliveries). Counting every excluded call as a coverage miss gives a worst-case floor of 77.8 percent; 6 of the 8 abstained, and counting the 2 that answered as errors gives a worst-case accuracy-when-answering of 88.9 percent. Both bounds ship in the report.
- Provenance on every surface: real phone channel, builder-answered scripted ground truth, consented builder line, never presented as calls to real practices. Reproduce: uv run python -m eval.study analyze on the committed scrubbed payloads.

## Class-conditional (Mondrian) findings (audited 2026-07-26)

- The marginal 90.3 percent coverage HID a per-class gap on the held-out fold: "no" answers were covered 83.2%, below the 90 percent target, while "unknown" sat at 100%. Class-conditional thresholds (one finite-sample-corrected quantile per true class) lift "no" to 88.5% and "yes" to 92.2%; overall Mondrian coverage 93.0%.
- Calibration-size sensitivity: coverage stays between 90.3 and 93.0 percent as the calibration fold shrinks from 300 to 50, so the guarantee is not an artifact of a large calibration set. Figure: eval/results/calibration_sensitivity.svg.
- Both hand-rolled in eval/conformal.py, seeded, regenerated by the one eval command. Headline metrics unchanged.

## Real-call facts (as of 2026-07-25)

- Two probe calls and one webhook-delivery test call placed through the seam, all to the builder's own phone with consent. First probe: no spoken response; the system reported `task_completed: false` rather than inventing an answer. Second probe: answered; `task_completed: true`, platform confidence 0.92.
- The scrubbed second-probe payload is the mock fixture (`mock_calle/fixtures/terminal_result.json`): phone and identifiers replaced with reserved fictional values, conversation verbatim.
- Platform findings, all verified empirically: the live API rejects both `result_schema` and `recipient_result_schema`; `webhook_url` is accepted but no webhook was delivered for a completed call (tunnel capture, 20+ minutes); terminal payloads are snake_case `call_task` objects with `recipients[].attempts[].transcript_turns`, `completion_confidence`, and `evidence`; there is no KYC gate before dialing.

## Judge sandbox facts (audited 2026-07-27)

- The judge key lets a judge have Attest call THEIR OWN number to experience the product live. Rails, all fail-closed and test-pinned: explicit StrictBool consent (422 without it); one call per phone number ever (SHA-256 hash, no number stored in the record); global cap of 15 (429); US +1 only with premium 900/976 and toll-950 prefixes rejected; kill switch ATTEST_SANDBOX_ENABLED=0 (503). Dedup and cap are enforced in ONE serialized SQLite transaction (sandbox_reservations table, PRIMARY KEY on the hash, count-in-transaction cap), so concurrent requests cannot bypass either rail even across workers.
- A second-model adversarial pass (Codex) found both rails were originally raceable (checked before the submission lock) and that consent is not proof of ownership; the races are fixed atomically. Accepted residual, stated plainly: a holder of the secret judge key could cause at most 15 disclosed, capped, one-per-number calls to numbers they do not own. The judge key is the access control and appears only in the judges-only Devpost testing instructions. Full ownership proof (OTP) needs an SMS provider we do not run.
- The operator key path is unrestricted and never railed; the two keys are distinct env vars.

## Mobile facts (audited 2026-07-27)

- Attest Pocket: Expo SDK 57 app in mobile/, read-only against the production API, no secrets in the binary, phone numbers masked server-side. Runs ledger, run detail (verdict stamp, claim cards, span-marked transcript synced to an expo-audio player of the receiving-end recording), PDF attestation certificate via the native share sheet, calibration screen with the real-telephone panel.
- Android: APK built on EAS with zero Apple involvement, hosted permanently as the GitHub release pocket-v0.1.0 asset (Expo artifact links expire in about 30 days and would die mid-judging). QR committed at docs/mobile/android-apk-qr.png.
- iOS: ad-hoc build installed on the builder's registered iPhone; store build 1.0.0 (3) APPROVED by Apple Beta App Review 2026-07-27 (verified against the App Store Connect API: betaReviewState APPROVED, processingState VALID), assigned to external group "Public Testers". The public link is a separate switch on that group and is NOT yet enabled, so no TestFlight URL exists yet. Add the link + QR only after the API reports publicLinkEnabled true and returns a publicLink; never claim the public link exists before it does.
- Watcher: a read-scoped ASC API key (attest-review-watch, .p8 in gitignored .secrets/) feeds a poller that checks betaReviewState every 30 minutes.

## Deployment facts

- Frontend: https://attest-web-phi.vercel.app (Vercel project `attest-web`). Note: `attest-web.vercel.app` (no suffix) is an unrelated third-party product.
- Backend: https://attest-api-o5gm.onrender.com (Render free tier, service `attest-api`, seeded on boot, database ephemeral by design).
- Keepalive: GitHub Actions cron at offset minutes `4,14,24,34,44,54`; verify by newest-run age, not green runs.
- Zero-credential judge path: `docker compose up --build` (api + mock + console; live dialing off).
- Live-call gate: `POST /internal/runs` requires the `X-Attest-Key` header; 403 on mismatch, 503 when unconfigured. Public API redacts every phone number (test-enforced).

## Audio evidence facts (audited 2026-07-26)

- The live CALL-E API exposes NO recording URL: verified field-by-field on the real terminal payload and by grepping the entire installed SDK (zero audio surface). Logged as feedback to the platform.
- Run audio therefore only exists when captured on our own end of a consented call and placed in ATTEST_AUDIO_DIR. The console's waveform player renders only when audio exists, always with a provenance label, and clicking an evidence span seeks playback to that turn.
- CI exercises the player with a synthetic alignment tone labeled "synthetic alignment tone, CI harness only" (ATTEST_SEED_TEST_TONE=1, set nowhere in production).
- Real audio shipped 2026-07-26: a consented builder-line call recorded on the receiving end by the builder, trimmed and loudness-normalized (25.6s, -17 LUFS integrated, mono AAC), scrubbed payload seeded as run_replay_builder_0001 with the label "audio captured on the receiving end of this consented call, builder line". Its verdict is honestly unverifiable at posterior 0.72: one agreeing field is +1.36 bits from an even prior, below the 0.85 verified bar. The extraction span is "Yes. We're we're accepting new patients." with real crosstalk earlier in the call.

## Landing film provenance (audited 2026-07-25)

- Hero film: Higgsfield Cinema Studio v2 (pro mode, 16:9, linear speedramp, sound off), prompt: single continuous extreme-macro journey from a telephone handset grille along copper wire to a nib writing in blue ink, ending on a brass notary seal. 12 credits.
- Post: ffmpeg minterpolate (mci) 24 to 60fps, h264 crf 22, keyframe every 8 frames, audio stripped. Measured shipped file: 7.97s, 1920x1080, 478 frames, 61 keyframes, 8.7MB, zero audio streams.
- Scrub safety is test-enforced: tests/test_film_asset.py parses the mp4 sync-sample table and fails if keyframes are sparser than one per half second; e2e drives a wheel stream to document end.

## Engineering facts

- Strict mypy; ruff lint + format in CI; gitleaks over full history in CI. Test and PR counts change on
  every merge, so they are recorded here as a dated snapshot and must be re-read before being quoted
  anywhere: **219 backend tests, 6 mobile tests, 55 merged PRs, as of 2026-07-27**. Regenerate with
  `uv run pytest --collect-only -q | tail -1` and
  `gh pr list --state merged --limit 100 --json number --jq 'length'`. Deliberately not repeated in the
  README, because a count duplicated across surfaces is a count that goes stale on one of them: that
  drift has now been caught three separate times on this repository.
- The upstream skill `skills/verify-by-phone` passes `validate_repository.py` from CALLE-AI/awesome-phone-call-agents staged against a clean clone (verified 2026-07-25). Upstream PR not yet opened.
- Second-model adversarial review found 7 verified issues in the loop/security wave (all fixed and regression-pinned); the harness twice caught confident-wrong extraction ("there's NO doctor's office here" parsing as a no; a plan claim stealing an unrelated span).

## Language rules for every artifact

- The eval dataset is scripted seeded scenario data and is labeled as such wherever it appears; real calls are the only thing presented as real calls.
- No em-dashes; no AI-marketing vocabulary; numbers always from this sheet's sources, never from memory.
