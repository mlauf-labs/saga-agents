"""Shared fixtures for runtime tests."""

from __future__ import annotations

import pytest

from saga_agents.config.models import (
    AgentDefinition,
    GlobalConfig,
    LangfuseSettings,
    Limits,
    McpSettings,
    OllamaSettings,
    RedisSettings,
    RuntimeSettings,
    ToolsSpec,
)


@pytest.fixture
def global_config() -> GlobalConfig:
    """Minimal GlobalConfig for unit tests (no real services required)."""
    return GlobalConfig(
        mcp=McpSettings(base_url="http://localhost:8100", bearer_token="test-token"),
        ollama=OllamaSettings(base_url="http://localhost:11434", default_model="qwen2.5:14b"),
        redis=RedisSettings(url="redis://localhost:6379", event_channel="saga.events"),
        langfuse=LangfuseSettings(),
        runtime=RuntimeSettings(),
    )


@pytest.fixture
def demo_definition() -> AgentDefinition:
    """Minimal autonomous AgentDefinition for unit tests."""
    return AgentDefinition(
        id="demo-agent",
        enabled=True,
        description="Demo agent for tests",
        model=None,
        autonomy="autonomous",
        tools=ToolsSpec(allow=["search_docs"], write=[]),
        limits=Limits(max_steps=10, max_tool_calls=20, timeout_seconds=30),
        system_prompt="You are a helpful assistant.",
    )


@pytest.fixture
def proposal_definition() -> AgentDefinition:
    """Proposal-mode AgentDefinition for proposal-sink tests."""
    return AgentDefinition(
        id="proposal-agent",
        enabled=True,
        description="Proposal agent for tests",
        model=None,
        autonomy="proposal",
        tools=ToolsSpec(allow=["search_docs", "delete_doc"], write=["delete_doc"]),
        limits=Limits(max_steps=10, max_tool_calls=20, timeout_seconds=30),
        system_prompt="You are a proposal agent.",
    )
