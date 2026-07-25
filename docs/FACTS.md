# Attest fact sheet

The single source every judge-facing artifact draws from: the README, the
Devpost submission, and the demo video narration all cite THIS file, and this
file cites the shipped code. Every entry lists where it was verified. If an
artifact needs a number that is not here, add it here first, with its audit.

Last audited: 2026-07-25.

## Product claims

| Claim | Verified against |
| --- | --- |
| CALL-E is imported and called at runtime via the official Python SDK | `backend/app/calle/client.py:13` (`from calle import CalleClient`); real calls placed through this seam on 2026-07-25 |
| Every extracted answer carries a verbatim span with character offsets, or abstains | `backend/app/extract.py` (`ExtractionResult.span_char_start/end`); enforced in `tests/test_artifact_two.py` |
| Hedge detection uses a graded lexicon that dampens trust proportionally | `backend/app/hedge.py` |
| Reconciliation is direct Fellegi-Sunter with fixed documented priors | `backend/app/reconcile.py` (`_FIELD_PARAMS`, `PRIOR_LOG_ODDS`) |
| The conformal core is implemented directly, finite-sample corrected | `eval/conformal.py` (`conformal_quantile`) |
| Do NOT claim: MAPIE, Splink, shadcn/ui | struck 2026-07-25; never imported anywhere (`grep -ri mapie\|splink` returns nothing in code) |

## Evaluation numbers (canonical: `eval/results/metrics.json`, seed 20260725)

| Number | Value |
| --- | --- |
| Scenario folds | 300 calibration / 300 held-out test, disjoint |
| Personas | cooperative, hedging, contradictory, evasive, wrong_number, refuses |
| Empirical coverage at 90% target | 90.3% (Wilson 95%: 86.5 to 93.2) |
| Abstention rate | 26.7% |
| Accuracy when answering | 94.5% |
| Error when forced to answer everything | 15.3% |
| Ablation: no hedge detection | accuracy-when-answering drops to 89.1% |
| Ablation: no dead-end guard | abstention doubles to 54.3%, accuracy still worse (89.8%) |
| Ablation: no calibration | 89.1% accuracy, no coverage guarantee at all |

Regeneration: `uv run python -m eval` reproduces every number and figure above on a clean checkout. Do not quote any eval number from memory; re-read `metrics.json`.

## Real-call facts (as of 2026-07-25)

- Two probe calls and one webhook-delivery test call placed through the seam, all to the builder's own phone with consent. First probe: no spoken response; the system reported `task_completed: false` rather than inventing an answer. Second probe: answered; `task_completed: true`, platform confidence 0.92.
- The scrubbed second-probe payload is the mock fixture (`mock_calle/fixtures/terminal_result.json`): phone and identifiers replaced with reserved fictional values, conversation verbatim.
- Platform findings, all verified empirically: the live API rejects both `result_schema` and `recipient_result_schema`; `webhook_url` is accepted but no webhook was delivered for a completed call (tunnel capture, 20+ minutes); terminal payloads are snake_case `call_task` objects with `recipients[].attempts[].transcript_turns`, `completion_confidence`, and `evidence`; there is no KYC gate before dialing.

## Deployment facts

- Frontend: https://attest-web-phi.vercel.app (Vercel project `attest-web`). Note: `attest-web.vercel.app` (no suffix) is an unrelated third-party product.
- Backend: https://attest-api-o5gm.onrender.com (Render free tier, service `attest-api`, seeded on boot, database ephemeral by design).
- Keepalive: GitHub Actions cron at offset minutes `4,14,24,34,44,54`; verify by newest-run age, not green runs.
- Zero-credential judge path: `docker compose up --build` (api + mock + console; live dialing off).
- Live-call gate: `POST /internal/runs` requires the `X-Attest-Key` header; 403 on mismatch, 503 when unconfigured. Public API redacts every phone number (test-enforced).

## Engineering facts

- 88 backend tests; strict mypy; ruff lint + format in CI; gitleaks over full history in CI; 13 merged PRs as of this audit (re-count with `gh pr list --state merged` before quoting).
- The upstream skill `skills/verify-by-phone` passes `validate_repository.py` from CALLE-AI/awesome-phone-call-agents staged against a clean clone (verified 2026-07-25). Upstream PR not yet opened.
- Second-model adversarial review found 7 verified issues in the loop/security wave (all fixed and regression-pinned); the harness twice caught confident-wrong extraction ("there's NO doctor's office here" parsing as a no; a plan claim stealing an unrelated span).

## Language rules for every artifact

- The eval dataset is scripted seeded scenario data and is labeled as such wherever it appears; real calls are the only thing presented as real calls.
- No em-dashes; no AI-marketing vocabulary; numbers always from this sheet's sources, never from memory.
