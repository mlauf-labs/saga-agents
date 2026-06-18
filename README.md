# saga-agents

Autonomous agent runner for the SAGA document archive. Reads agent definitions
from Markdown files, listens for SAGA events (Redis pub/sub), fires on cron
schedules or external HTTP triggers, and calls SAGA's MCP tools — either
directly (autonomous mode) or via a human-approval step (proposal mode).

---

## How agents are defined

Each agent is a single `.md` file in `config/agents/` with a YAML frontmatter
block followed by the system prompt body.

```markdown
---
id: my-agent
enabled: true
description: "One-line description."
autonomy: proposal          # or: autonomous
model: llama3.1:8b          # optional; falls back to AGENTS_DEFAULT_MODEL
tools:
  allow: [get_document, hybrid_search, update_event]
  write: [update_event]
triggers:
  - type: event
    topics: [document.ingested]
    debounce_minutes: 10
  - type: schedule
    cron: "0 3 * * *"
  - type: external
limits:
  max_steps: 40
  max_tool_calls: 100
  timeout_seconds: 900
  max_concurrent_runs: 1
---

You are the **My Agent** for the SAGA document archive.
(System prompt continues here …)
```

---

## Trigger types

| Type | Description |
|------|-------------|
| `event` | Fires when a matching topic is published on the Redis event channel. Supports `debounce_minutes` — the agent runs only after `debounce_minutes` minutes of silence since the last matching event. |
| `schedule` | Fires on a 5-field cron expression (`"0 3 * * *"` = daily at 03:00 UTC). |
| `external` | Fires only when `POST /triggers/{agent_id}` is called with a valid bearer token. |

An agent may have any combination of trigger types.

---

## Autonomy modes and proposals

### `autonomous`

The agent calls write-capable MCP tools directly. Use for fully trusted,
low-risk maintenance tasks.

### `proposal` (default)

Write tools are hidden from the agent. Instead, the agent calls a built-in
`propose` tool that records an intended action (MCP tool name + arguments +
rationale) to the local SQLite store without executing it.

Operators review and approve or reject proposals through the REST API:

```
GET  /agents/{agent_id}/proposals          # list pending proposals
POST /proposals/{proposal_id}/approve      # execute and mark applied
POST /proposals/{proposal_id}/reject       # discard
```

All endpoints require `Authorization: Bearer <AGENTS_EXTERNAL_TOKEN>`.

---

## How to run

### Development (local)

```bash
cd saga-agents
cp .env.example .env          # fill in SAGA_MCP_URL, SAGA_MCP_TOKEN, etc.

# Export env vars and start:
export $(grep -v '^#' .env | xargs)
uv run saga-agents
```

The API is available at `http://localhost:8099`.

### Docker (standalone)

```bash
docker compose up -d --build
```

### Docker (full SAGA stack, from workspace root)

```bash
cd ..                          # workspace root (Archiv/)
docker compose up -d --build
```

### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SAGA_MCP_URL` | Yes | `http://localhost:8100` | SAGA MCP server endpoint |
| `SAGA_MCP_TOKEN` | Yes | — | Bearer token for MCP server |
| `OLLAMA_URL` | Yes | `http://localhost:11434` | Ollama API endpoint |
| `AGENTS_DEFAULT_MODEL` | No | `llama3.1:8b` | Default LLM model |
| `REDIS_URL` | Yes | `redis://localhost:6379/0` | Redis connection URL |
| `SAGA_EVENT_CHANNEL` | No | `saga.events` | Redis pub/sub channel |
| `LANGFUSE_PUBLIC_KEY` | No | — | Langfuse tracing (optional) |
| `LANGFUSE_SECRET_KEY` | No | — | Langfuse tracing (optional) |
| `LANGFUSE_HOST` | No | `https://cloud.langfuse.com` | Langfuse endpoint |
| `AGENTS_EXTERNAL_TOKEN` | Yes | `changeme` | Token for external trigger API |
| `AGENTS_PORT` | No | `8099` | Listening port |
| `SAGA_AGENTS_CONFIG` | No | `config/agents.yaml` | Path to global config file |

---

## Adding a new agent

1. Create a new file `config/agents/<your-agent-id>.md`.
2. Add the YAML frontmatter (id, triggers, tools, autonomy, limits).
3. Write the system prompt as the file body.
4. Restart saga-agents (or the Docker container).

No code changes are required. The loader picks up all `*.md` files in
`config/agents/` automatically at startup.

---

## Reference agents

| Agent | File | Triggers | Mode |
|-------|------|----------|------|
| `event-deduplicator` | `config/agents/event-deduplicator.md` | event + schedule + external | proposal |
| `re-categorizer` | `config/agents/re-categorizer.md` | schedule + external | proposal |

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Liveness probe (no auth) |
| `POST` | `/triggers/{agent_id}` | Trigger an agent run (bearer auth) |
| `GET` | `/agents/{agent_id}/proposals` | List pending proposals (bearer auth) |
| `POST` | `/proposals/{id}/approve` | Approve and apply a proposal (bearer auth) |
| `POST` | `/proposals/{id}/reject` | Reject a proposal (bearer auth) |
