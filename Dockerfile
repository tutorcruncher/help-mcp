# Single-stage Python image. Unlike git-mcp there is no backend binary to vendor —
# this server defines its own tools and fetches docs over HTTPS at request time.
FROM python:3.12-slim-bookworm

# uv for dependency management (copied from the official uv image, pinned by digest).
COPY --from=ghcr.io/astral-sh/uv:0.11.21@sha256:ff07b86af50d4d9391d9daf4ff89ce427bc544f9aae87057e69a1cc0aa369946 /uv /uvx /usr/local/bin/

WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# Install dependencies first (layer-cached on lockfile changes only).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code.
COPY app ./app

# Heroku provides $PORT at runtime; app.server binds 0.0.0.0:$PORT.
CMD ["python", "-m", "app.server"]
