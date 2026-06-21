# Changelog

All notable changes to this project are documented here. This project follows
[Conventional Commits](https://www.conventionalcommits.org/); release notes are
generated from the commit history (see `cliff.toml` and the release workflow).

## [Unreleased]

### Features

- **agents**: declarative agent definitions — one Markdown file per agent
  (`config/agents/*.md`) with YAML frontmatter (id, autonomy, model, tools,
  triggers, limits) and a system-prompt body; the loader picks up every file at
  startup with no code changes required.
- **triggers**: three trigger types per agent — `event` (Redis pub/sub topics with
  optional debounce), `schedule` (cron expressions via APScheduler), and `external`
  (`POST /triggers/{agent_id}` with bearer auth).
- **runtime**: Pydantic AI run loop calling SAGA's MCP tools, with per-run guardrails
  (`max_steps`, `max_tool_calls`, `timeout_seconds`, `max_concurrent_runs`) and
  `{{saga.*}}` guidance placeholders resolved from SAGA per run.
- **proposals**: `proposal` autonomy mode (default) records intended MCP calls to a
  local SQLite store via a built-in `propose` tool; operators review and approve or
  reject them through the REST API, which executes approved calls.
- **observability**: OpenTelemetry / Langfuse tracing with the trace id captured into
  the run report, plus a Prometheus `/metrics` endpoint and `/stats` for run and
  proposal counters.
- **packaging**: standalone `Dockerfile` and `docker-compose.yml` (expects an external
  SAGA stack + Redis); configurable entirely via environment variables.
