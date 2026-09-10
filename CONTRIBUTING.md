# Contributing

Attest is a hackathon build (CALL-E: Your Code Is Calling, Sep 2026), so the
bar for merging during judging is high, but issues and PRs are welcome.

- Keep user-visible evidence reproducible: no secrets or real phone numbers in
  the repository, and regenerate reported measurements with
  `uv run python -m eval` rather than typing them into documentation.
- Before a PR, run the full gate:
  `uv run ruff check . && uv run ruff format --check . && uv run mypy tests backend eval mock_calle scripts && uv run pytest`
  plus `cd frontend && pnpm exec tsc --noEmit`.
- Changes to the calling path need a mock-server test; no automated test ever
  places a real phone call.
- Changes that touch calibration must keep the calibration and test folds
  disjoint, and must regenerate `eval/results/` in the same commit.
- Phone numbers in code, tests, and fixtures use the reserved fictional
  range (`+15550101234`). Never a real number.
