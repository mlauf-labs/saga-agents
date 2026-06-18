FROM python:3.12-slim AS base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Install dependencies first (layer-cached until pyproject/lockfile change)
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen || uv sync --no-dev

# Copy application source and config
COPY src ./src
COPY config ./config

# Install the package itself (non-editable, into the existing .venv)
RUN uv sync --no-dev --no-editable || true

# Point at the config file baked into the image; operators can override via
# -e SAGA_AGENTS_CONFIG or a mounted config volume.
ENV SAGA_AGENTS_CONFIG=config/agents.yaml

CMD ["uv", "run", "saga-agents"]
