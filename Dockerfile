FROM python:3.12-slim AS base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Install dependencies first (layer-cached until pyproject/lockfile change).
# --no-install-project: build only the dependency env here; the project itself is
# built after its sources (and README, referenced by [project].readme) are copied.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project --frozen || uv sync --no-dev --no-install-project

# Copy application source and config
COPY src ./src
COPY config ./config
# README.md is referenced by pyproject ([project].readme); uv needs it to build the project.
COPY README.md ./README.md

# Install the package itself (non-editable, into the existing .venv)
RUN uv sync --no-dev --no-editable

# Point at the config file baked into the image; operators can override via
# -e SAGA_AGENTS_CONFIG or a mounted config volume.
ENV SAGA_AGENTS_CONFIG=config/agents.yaml

# --no-dev keeps the runtime env in sync with the build's `uv sync --no-dev`, so
# starting the container does not re-pull dev deps (ruff/mypy).
CMD ["uv", "run", "--no-dev", "saga-agents"]
