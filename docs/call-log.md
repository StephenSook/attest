# Real-call log

Every real CALL-E call this project places gets a row here. Development runs
against mock_calle only; no automated test ever dials.

| # | Date (UTC) | Budget line | Recipient | Outcome |
| - | ---------- | ----------- | --------- | ------- |
| 1 | 2026-07-25 | probe | builder's own phone, consented | No spoken response; platform reported task_completed false rather than inventing an answer. Payload shape captured. |
| 2 | 2026-07-25 | probe | builder's own phone, consented | Answered; task_completed true, platform confidence 0.92. Scrubbed payload became mock_calle/fixtures/terminal_result.json. |
| 3 | 2026-07-25 | webhook live test | builder's own phone, consented | Call completed; webhook_url accepted at creation but no delivery observed in 20+ minutes of tunnel capture. Poller confirmed authoritative. |
| 4 | 2026-07-26 | probe | builder's own phone, consented | Audio-evidence take: answered yes to accepting new patients; task_completed true, platform confidence 0.95. Receiving-end recording captured by the builder, trimmed and normalized (25.6s, -17 LUFS), shipped as the run_replay_builder_0001 replay with audio. |

| 5-40 | 2026-07-26/27 | real-call validation | builder's own phone, consented | Real-channel transfer study, 36 pre-registered scripted calls across three sessions. Per-call records: eval/study_data/manifest.json (ground truth, deviation protocol, exclusions) and eval/study_data/calls/. Result: 28/28 coverage at the harness threshold. |

| 41 | 2026-07-28 | demo takes | a consenting Atlanta counseling practice, first third-party recipient | The practice consented in writing to one call and to public use of the transcript, choosing to remain anonymous. Reached voicemail. The agent obeyed the no-message rule and ended the call during the greeting without leaving anything. Platform reported `task_completed: false` with three explicit evidence lines saying no answer was obtained. Attest abstained on all three claims, verdict `unverifiable`, posterior 0.5, the untouched prior. Scrubbed payload shipped as `run_replay_practice_0001`. |

| 42 | 2026-09-09 | post-KYC hotline canary | CALL-E's published testing hotline | After Persona verification and selecting the dedicated US number as the default outbound line, the official SDK seam completed one platform-owned test call. The terminal result reported `task_completed: true`, confidence 0.90 (high), and no failure. The raw payload remains gitignored. |

| 43 | 2026-09-12 | demo takes | builder's own phone, consented, scripted ground truth | Demo v2 take 1, placed through the product's own form on the local live stack (operator key, record claiming accepting: yes, no plan). Answered; the builder gave the scripted "no" on new patients. Platform `task_completed: true`, confidence 0.95. Attest extracted office yes (+1.66 bits) and accepting no (-2.70 bits), posterior 0.33, verdict `unverifiable`: one contradiction against a confirmed identity does not clear the 0.30 contradicted line. Screen capture failed (wrong window, silent mic); not used in the film. |

| 44 | 2026-09-12 | demo takes | builder's own phone, consented, scripted ground truth | Demo v2 take 2, same form path with the record also claiming Aetna PPO. The phone was on Do Not Disturb, so the call reached voicemail. Platform `task_completed: false`, confidence 0.88. Attest abstained on all three claims, posterior 0.50, verdict `unverifiable`. Page recording and log kept as a voicemail artifact. |

| 45 | 2026-09-12 | demo takes | builder's own phone, consented, scripted ground truth | Demo v2 take 3, the film take. Record claimed accepting: yes and plan Aetna PPO; the builder answered yes to identity and no to both. Platform `task_completed: true`, confidence 0.95. Attest cited all three spans, office yes (+1.66), accepting no (-2.70), plan no (-2.32), posterior 0.09, verdict `contradicted`. Browser recorded by Playwright page video (176.6 s, 1280x800); the builder and the phone recorded on a second phone camera. Raw payload stays in the gitignored local database; phone masked in every UI surface. |

Note on call 41: no audio exists for it. The Calls API and Python SDK expose no recording URL, and unlike the builder-line calls we were the caller rather than the receiver, so there was no end of the line we could lawfully or technically record. The transcript is the whole artifact.
