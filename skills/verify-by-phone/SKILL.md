---
name: verify-by-phone
description: Verify a directory listing, database record, or any published claim about an organization by placing one disclosed CALL-E phone call and returning a span-grounded structured answer with a calibrated confidence or an explicit abstention. Use when stored information about a business must be checked against reality by phone, such as provider directory entries, accepting-new-patients status, insurance participation, hours, or availability, and when a wrong answer is more costly than no answer.
license: MIT
---

# Verify By Phone

Use this skill when an agent must establish whether stored information about an organization is still true, and a phone call to the organization's published line is the way to find out.

`verify-by-phone` is a verification workflow skill. It places exactly one disclosed outbound CALL-E call per record, extracts the answer from the transcript with a verbatim supporting span, reconciles it against the stored record with transparent match-weight arithmetic, and returns either a calibrated confidence or an explicit abstention. The design goal is an agent that never converts an uncertain phone answer into a confident database write.

## When To Use

Use this skill for:

- verifying a provider directory listing: is this practice real, reachable, accepting new patients, taking a given insurance plan
- checking whether a stored business record (hours, services, availability) still matches reality
- refreshing any dataset where the phone is the source of truth and the record is suspected stale
- workflows where an "unknown" outcome must be recorded honestly instead of guessed
- one record at a time, with a human-authorized recipient list

## When Not To Use

Do not use this skill to:

- place undisclosed or pretext calls; every call announces that it is an automated assistant and why it is calling, in the same breath
- call wireless or personal numbers; verification targets published organizational lines
- run marketing, sales, lead generation, or any promotional outreach
- batch-dial a list without per-record human authorization
- overwrite a stored record directly from a call result; the output is a verdict with evidence, and the write decision stays with the operator
- guess an answer the respondent did not give; if the call yields no usable answer, the result is an abstention, and that is the correct output

## Consent And Disclosure Rules

These are load-bearing, not boilerplate:

1. The call opens by stating the AI identity and the purpose together, before anything else, and announces that the call may be recorded.
2. If the respondent objects to speaking with an automated caller, the call thanks them and ends immediately. The result records the refusal as an unverifiable outcome.
3. Hold time is capped. If the respondent asks the caller to wait, it waits briefly, then reports back rather than waiting indefinitely.
4. The agent never invents information it was not given, on the call or in the result.
5. Calls are informational verification, never promotional. Treat every call as recorded with all-party consent requirements in mind.

## Verification Workflow

1. Collect the record to verify: organization name, published phone number in E.164, and the claims to check (for example accepting new patients, accepts a named plan).
2. Confirm the operator authorizes this specific call to this specific number.
3. Build the call task with `scripts/place_verify_call.py`. The script defaults to a dry run that prints the exact task and recipient without dialing; pass `--live` only after the dry run looks right.
4. Poll for the terminal result with `scripts/poll_result.py`, which saves the full payload to a local file.
5. Extract the answer with `scripts/extract_answer.py`. Every extracted field carries the verbatim transcript span and character offsets that support it. Hedged answers ("I think so") keep their polarity at a dampened trust score. Non-responsive turns (wrong number, refusal, "call back later") never count as answers.
6. Reconcile against the stored record with `scripts/reconcile_record.py`: each agreeing field adds documented bits of evidence, each disagreeing field subtracts them, and the verdict is verified, contradicted, or unverifiable.
7. Calibrate the abstention threshold with `scripts/calibrate.py` on labeled scenario data, so "confident" means something measurable: at the default level, the true answer falls inside the prediction set at least 90 percent of the time on held-out data, and the system abstains rather than answer when the set is not a single value.

## Quick Start

```bash
pip install calle-ai

# 1. Dry run: prints the task and masked recipient, dials nothing.
python3 scripts/place_verify_call.py \
  --org "Example Counseling Center" \
  --phone "+15550101234" \
  --claim-accepting-new-patients yes \
  --claim-plan "Example Health PPO"

# 2. Place the call for real (requires CALLE_API_KEY).
python3 scripts/place_verify_call.py ... --live

# 3. Wait for the terminal payload.
python3 scripts/poll_result.py --call-id call_abc123 --out result.json

# 4. Extract the span-grounded answer.
python3 scripts/extract_answer.py --payload result.json

# 5. Reconcile against the stored record.
python3 scripts/reconcile_record.py --payload result.json \
  --claim-accepting-new-patients yes --claim-plan-accepted yes

# 6. Calibrate the abstention threshold on labeled scenarios.
python3 scripts/calibrate.py --data references/sample-scenarios.jsonl --alpha 0.1
```

All sample numbers in this skill are reserved fictional numbers. The dry run path and the bundled scenario data mean everything except step 2 runs with no credentials and no real call.

## What The Output Looks Like

`extract_answer.py` emits one JSON object per claim:

```json
{
  "claim": "accepting_new_patients",
  "answer": "yes",
  "trust_score": 0.9,
  "hedged": false,
  "span": {"turn": 6, "text": "Yep.", "char_start": 0, "char_end": 3},
  "abstain": false
}
```

An abstention keeps the same shape with `"answer": "unknown"` and `"abstain": true`. `reconcile_record.py` adds the match-weight arithmetic and a verdict. No field ever appears without either a supporting span or an explicit abstention.

## Side Effects And Cancellation

- Side effect: exactly one outbound phone call per `--live` invocation, to the number the operator supplied. Nothing recurs; there is no scheduler in this skill.
- Cost: one billable CALL-E call per live run. Dry runs are free.
- Cancellation: CALL-E does not expose call cancellation, so the moment to stop is before `--live`. The dry-run default exists for exactly that reason.
- Data: payloads are written to local files the operator names. Phone numbers are masked in console output. Nothing in this skill transmits results anywhere except the CALL-E API itself.

## References

- `references/api-notes.md`: the empirically observed CALL-E payload shape and API behaviors this skill relies on, including facts that were discovered by testing rather than documentation.
- `references/verification-protocol.md`: the full disclosure script, the legal posture for outbound verification calls, and why abstention is the core design decision.
- `references/sample-scenarios.jsonl`: labeled fictional scenario data used by `scripts/calibrate.py`, so calibration runs with no credentials and no calls.
