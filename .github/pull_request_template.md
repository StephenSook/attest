## What

One logical change per PR. What does this do, and why now?

## Verification

- [ ] `uv run ruff check .` and `uv run ruff format --check .`
- [ ] `uv run mypy tests backend eval mock_calle scripts`
- [ ] `uv run pytest`
- [ ] `cd frontend && pnpm exec tsc --noEmit`
- [ ] e2e (`pnpm exec playwright test` against `docker compose up`) if this
      touches a served surface
- [ ] If any reported number changed: `uv run python -m eval` regenerated and
      the README, `docs/FACTS.md`, and the console agree

## Claims

- [ ] Every tool, model, or integration named in this PR is actually called
      at runtime (wired or cut)
- [ ] No fabricated or simulated data is presented as real anywhere
      judge-facing
- [ ] No secrets, no real phone numbers, no third-party PII
