"""Pydantic models for saga-agents configuration.

GlobalConfig is loaded from ``config/agents.yaml``.
AgentDefinition is loaded from per-agent ``*.md`` files with YAML frontmatter.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, field_validator

from saga_agents.core.errors import ConfigError

# ---------------------------------------------------------------------------
# Trigger models
# ---------------------------------------------------------------------------


class EventTrigger(BaseModel):
    """Fire when one of the listed saga events is emitted."""

    type: Literal["event"]
    on: list[str]
    debounce_minutes: int = 0


class ScheduleTrigger(BaseModel):
    """Fire on a cron schedule."""

    type: Literal["schedule"]
    cron: str


class ExternalTrigger(BaseModel):
    """Fire only when triggered explicitly via the REST API."""

    type: Literal["external"]


Trigger = Annotated[
    Union[EventTrigger, ScheduleTrigger, ExternalTrigger],
    Field(discriminator="type"),
]

# ---------------------------------------------------------------------------
# ToolsSpec
# ---------------------------------------------------------------------------


class ToolsSpec(BaseModel):
    """Declares which MCP tools an agent may use and which allow writes."""

    allow: list[str] = Field(default_factory=list)
    write: list[str] = Field(default_factory=list)

    @field_validator("write", mode="after")
    @classmethod
    def _write_subset_of_allow(cls, write: list[str], info: Any) -> list[str]:
        allow: list[str] = info.data.get("allow", [])
        extra = set(write) - set(allow)
        if extra:
            raise ConfigError(
                f"ToolsSpec.write contains tools not in allow: {sorted(extra)}"
            )
        return write


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


class Limits(BaseModel):
    """Per-agent execution limits."""

    max_steps: int = 40
    max_tool_calls: int = 100
    timeout_seconds: int = 900
    max_concurrent_runs: int = 1


# ---------------------------------------------------------------------------
# AgentDefinition
# ---------------------------------------------------------------------------


class AgentDefinition(BaseModel):
    """Full definition of a single agent, merged from frontmatter + body."""

    id: str
    enabled: bool = True
    description: str = ""
    model: str | None = None
    autonomy: Literal["proposal", "autonomous"] = "proposal"
    tools: ToolsSpec = Field(default_factory=ToolsSpec)
    triggers: list[Trigger] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)
    context: dict[str, Any] = Field(default_factory=dict)
    system_prompt: str = ""


# ---------------------------------------------------------------------------
# Infrastructure settings
# ---------------------------------------------------------------------------


class McpSettings(BaseModel):
    """Connection settings for the Saga MCP server."""

    base_url: str
    bearer_token: str


class OllamaSettings(BaseModel):
    """Connection settings for the local Ollama instance."""

    base_url: str
    default_model: str


class RedisSettings(BaseModel):
    """Connection settings for Redis (job queue + event pub/sub)."""

    url: str
    event_channel: str


class LangfuseSettings(BaseModel):
    """Optional Langfuse observability integration."""

    public_key: str = ""
    secret_key: str = ""
    host: str = "https://cloud.langfuse.com"


class RuntimeSettings(BaseModel):
    """Global runtime behaviour tunables."""

    max_concurrent_runs_global: int = 2
    proposals_db: str = "proposals.db"


# ---------------------------------------------------------------------------
# GlobalConfig
# ---------------------------------------------------------------------------


class GlobalConfig(BaseModel):
    """Root configuration object, loaded from ``config/agents.yaml``."""

    mcp: McpSettings
    ollama: OllamaSettings
    redis: RedisSettings
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    agents_dir: str = "config/agents"
