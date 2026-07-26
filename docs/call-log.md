# Real-call log

Every real CALL-E call this project places gets a row here, logged against the
budget lines in CONSTITUTION.md. Development runs against mock_calle only; no
automated test ever dials.

| # | Date (UTC) | Budget line | Recipient | Outcome |
| - | ---------- | ----------- | --------- | ------- |
| 1 | 2026-07-25 | probe | builder's own phone, consented | No spoken response; platform reported task_completed false rather than inventing an answer. Payload shape captured. |
| 2 | 2026-07-25 | probe | builder's own phone, consented | Answered; task_completed true, platform confidence 0.92. Scrubbed payload became mock_calle/fixtures/terminal_result.json. |
| 3 | 2026-07-25 | webhook live test | builder's own phone, consented | Call completed; webhook_url accepted at creation but no delivery observed in 20+ minutes of tunnel capture. Poller confirmed authoritative. |
| 4 | 2026-07-26 | probe | builder's own phone, consented | Audio-evidence take: answered yes to accepting new patients; task_completed true, platform confidence 0.95. Receiving-end recording captured by the builder, trimmed and normalized (25.6s, -17 LUFS), shipped as the run_replay_builder_0001 replay with audio. |

Remaining allocation (of 20 pre-credit calls): probe/fixture 0 of 3 left, webhook test 1 of 2 left, real-call validation 6, demo takes 6, reserve 3. The ~200 promotional credits extend real-call validation only, not this logging rule.
