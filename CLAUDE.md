# CLAUDE.md

Guidance for Claude / AI coding agents working in **SAGA Agents** — the autonomous agent
runner for **SAGA** (*Self-organizing Archive for Generative Agents*). Read this before making
any change. Keep changes small, focused, typed, tested, and consistent with the conventions
below.

## Project overview

A Python service that runs autonomous LLM agents against the SAGA archive. Agents are defined
declaratively as Markdown files (YAML frontmatter + system prompt) in `config/agents/`. The
runner listens for SAGA events (Redis pub/sub), fires on cron schedules or external HTTP
triggers, and calls SAGA's **MCP tools** — either directly (`autonomous` mode) or via a
human-approval step (`proposal` mode, the default). It talks to SAGA exclusively over the
**MCP server** (HTTP); it does not access the database or object storage directly.

Built on **Pydantic AI**. A FastAPI app exposes health, trigger, and proposal-review
endpoints (default port **8099**). Runs and proposals are observable via OpenTelemetry /
Langfuse tracing and a Prometheus `/metrics` endpoint.

## Tech stack & requirements

- **Python 3.12+, fully typed** (`uv run mypy` strict must pass).
- **Pydantic AI** (agents) · **FastAPI** + **uvicorn** (API) · **APScheduler** (cron) ·
  **Redis** (event pub/sub) · **aiosqlite** (proposal store).
- LLM via **Ollama** (default) or any OpenAI-compatible endpoint.
- Tracing: **logfire** / OpenTelemetry → **Langfuse** (optional). Metrics: **prometheus-client**.
- **`uv`** for dependency & env management. Distribution name **`saga-agents`**, import
  package **`saga_agents`**.

## Repository layout

```
src/saga_agents/
  app.py            # entrypoint: build + wire the FastAPI app and triggers
  config/           # global config + agent-definition loader (loader.py, models.py)
  core/             # env, errors, structured logging
  runtime/          # agent run loop: model, toolset, runner, propose, guidance, report
  triggers/         # event (Redis), schedule (cron), external (HTTP) triggers + executor
  proposals/        # SQLite proposal store + apply (execute approved MCP calls)
  metrics/          # Prometheus registry
  tracing/          # Langfuse / OTel wiring
config/
  agents.yaml       # global config (defaults, limits)
  agents/*.md       # one Markdown file per agent (YAML frontmatter + system prompt)
tests/              # pytest (mirrors src layout)
Dockerfile          # python:3.12-slim + uv
docker-compose.yml  # standalone compose (expects an external SAGA stack + Redis)
```

## Common commands

```bash
uv sync                       # install deps
uv run ruff check . --fix     # lint + autofix
uv run ruff format .          # format
uv run mypy                   # strict type check
uv run pytest                 # tests
uv run pre-commit install && uv run pre-commit install --hook-type commit-msg

# Run the service (needs SAGA MCP + Redis reachable; see .env.example):
uv run saga-agents            # API on :8099

# Docker (expects an external SAGA stack):
docker compose up -d --build
```

Run lint, type-check, and tests before considering a change done — they must be green.

## Agent definitions

Each agent is a single `.md` file in `config/agents/` with a YAML frontmatter block (id,
`enabled`, `autonomy`, `model`, `tools.allow`/`tools.write`, `triggers`, `limits`) followed
by the system prompt body. **No code changes are required to add an agent** — the loader
picks up every `*.md` file at startup. See [`README.md`](README.md) for the full schema and
the two reference agents (`event-deduplicator`, `re-categorizer`).

## Key constraints (watch out for these)

- **MCP-only access to SAGA.** This service reaches SAGA exclusively through the MCP server
  over HTTP. Never add direct PostgreSQL / MinIO / OpenSearch access — that is saga-core's and
  saga-backup's domain. MCP tool descriptions live in saga-core, not here.
- **Proposal mode is the safe default.** In `proposal` mode, write-capable tools are hidden
  from the agent; it calls the built-in `propose` tool, which records the intended MCP call to
  the SQLite store without executing it. Approval (`POST /proposals/{id}/approve`) is what
  actually executes the call. Don't let an agent write directly unless its definition opts into
  `autonomy: autonomous`.
- **Respect run limits.** `max_steps`, `max_tool_calls`, `timeout_seconds`, and
  `max_concurrent_runs` come from each agent's `limits` (with `agents.yaml` defaults). Don't
  bypass them; they are the guardrails against runaway runs.
- **Config over constants.** No hard-coded endpoints, models, tokens, or limits. Read from
  `config/*.yaml`, agent frontmatter, and env; secrets only via env / `.env`.
- **`{{saga.*}}` guidance placeholders** in prompts are resolved per run from SAGA; a fetch
  failure is an error, not a silent fallback. Don't inline guidance that belongs in SAGA.
- **Actionable errors.** Raise from the `saga_agents.core.errors` hierarchy with messages
  saying what failed and how to fix it. No bare/silent failures.
- **Structured logging.** Use `saga_agents.core.logging`; never `print`. Bind run / agent ids
  where relevant so logs link to the OTel trace id.
- **Secrets only via env** (`SAGA_MCP_TOKEN`, `AGENTS_EXTERNAL_TOKEN`, Langfuse keys). Never
  log or commit them.
- **English only** — code, comments, identifiers, docs, commits.

## Configuration (env)

`SAGA_MCP_URL` · `SAGA_MCP_TOKEN` · `OLLAMA_URL` · `AGENTS_DEFAULT_MODEL` · `REDIS_URL` ·
`SAGA_EVENT_CHANNEL` · `AGENTS_EXTERNAL_TOKEN` · `AGENTS_PORT` · `SAGA_AGENTS_CONFIG` ·
`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` (optional). See
[`.env.example`](.env.example) and the README configuration table.

## Coding conventions

- Every function/attribute annotated; avoid `Any` unless unavoidable and justified.
- New/changed logic ships with pytest tests (mock SAGA MCP, Redis, and the LLM — unit tests
  must not require live services). `asyncio_mode = auto`.
- Add deps with `uv add <pkg>` / `uv add --dev <pkg>`; never hand-edit versions without
  updating `uv.lock`. No secrets committed.

## Git workflow — branching, commits, PRs

**`main` and `develop` are protected**: pull requests are required, and only the repository
**admin/owner** may push directly (force-push and deletion are blocked). **Do not push
directly to `main`/`develop`** — always use a feature branch + PR.

- `main` — stable/release branch. `develop` — integration branch; feature work branches here.

```bash
git switch develop && git pull
git switch -c feature/<short-description>   # or fix/… , docs/… , chore/… , refactor/…
# …focused commits…
git push -u origin feature/<short-description>
gh pr create --base develop --fill          # PR targets develop
```

After review + green CI, **squash-merge** into `develop`. Promote to `main` via a
`develop → main` PR; tag `vX.Y.Z` on `main` for releases.

**Commits**
- Only commit or push **when the human explicitly asks.** If you're on `main`/`develop`,
  branch first.
- **Conventional Commits**, imperative, English (`feat:`, `fix:`, `docs:`, `refactor:`,
  `test:`, `chore:`, `ci:`, `build:`, `perf:`). A `commit-msg` pre-commit hook enforces this.
- Never `--no-verify`, never commit secrets or build artifacts.

## CI

`.github/workflows/ci.yml` runs on push/PR to `main` and `develop`: lint + strict type-check
+ tests, then a no-push Docker image build. Keep it green; update the workflow in the same PR
as the code it covers. `release.yml` generates release notes from Conventional Commits when a
`v*` tag is pushed.

## Definition of done

Typed, linted, type-checked, tested. No secrets committed; config-driven; errors actionable;
logs structured. Proposal/approval safety intact; agent run limits respected. User-visible
behaviour documented in `README.md` (and `CHANGELOG.md` if notable).
