FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY backend ./backend
COPY mock_calle ./mock_calle
COPY eval ./eval
COPY scripts ./scripts

RUN uv sync --frozen

EXPOSE 8000
CMD ["sh", "-c", "uv run python scripts/seed_replay.py && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]
