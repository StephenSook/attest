# Attest

**The phone agent that refuses to guess.**

Attest places one goal-driven outbound phone call to a healthcare provider's published line, captures a schema-validated structured result where every field cites a verbatim span of the call transcript, reconciles the answer against the directory record, and returns either a calibrated confidence or an explicit abstention with a distribution-free coverage guarantee computed on held-out data.

Built on [CALL-E](https://github.com/CALLE-AI/call-e-integrations) for the CALL-E: Your Code Is Calling hackathon.

## Status

Early scaffold. The build plan, gates, and definition of done live in [CONSTITUTION.md](CONSTITUTION.md).

## Commands

```bash
uv sync                                  # backend dependencies
uv run uvicorn app.main:app --reload     # backend API
uv run uvicorn mock_calle.server:app --port 8100   # mock CALL-E server
uv run pytest                            # tests (mock server only, no real calls)
```

## Repository layout

```
backend/app/      FastAPI backend; backend/app/calle/ is the CALL-E integration seam
mock_calle/       standalone mock of the CALL-E API surface used by every test
tests/            pytest suite, runs with no credentials and no real calls
eval/             seeded evaluation harness (regenerates every reported number)
skills/           the Agent Skill contributed upstream (added later)
frontend/         Vite + React app (added later)
```

## License

MIT
