# hotel-mcp: one image for Railway, Hugging Face Spaces and local Docker.
# Build from this directory:  docker build -t hotel-mcp apps/mcp-server
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Dependencies first so code changes don't re-download them. (No BuildKit cache mounts:
# Railway rejects them without a Railway-specific id.)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN uv sync --locked --no-dev

# UID 1000: Hugging Face Spaces runs containers as this user; harmless elsewhere.
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000
# Apply migrations on every start (idempotent), then serve on $PORT. Seeding stays a manual step.
CMD ["sh", "-c", "hotel-mcp migrate && exec hotel-mcp serve"]
