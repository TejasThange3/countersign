# countersign-agent: the voice agent for Railway (or any Docker host).
# Build from this directory:  docker build -t countersign-agent apps/agent
# Hosted speech-to-text (STT_PROVIDER=groq) needs no GPU; the local Whisper model is only
# downloaded if STT_PROVIDER=whisper is chosen.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

# libgomp1: OpenMP runtime that onnxruntime (Silero VAD, Smart Turn) loads.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    AGENT_HOST=0.0.0.0 \
    STT_PROVIDER=groq \
    PORT=7860

WORKDIR /app

# Dependencies first so code changes don't re-download them.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 7860
# Railway assigns $PORT; the agent reads AGENT_PORT.
CMD ["sh", "-c", "AGENT_PORT=${PORT} exec python -m countersign_agent.app"]
