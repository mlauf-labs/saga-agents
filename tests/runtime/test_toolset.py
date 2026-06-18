"""Tests for MCP server factory and visible_tool_names."""

from __future__ import annotations

from saga_agents.config.models import ToolsSpec
from saga_agents.runtime.toolset import visible_tool_names


def test_autonomous_sees_all_allowed() -> None:
    spec = ToolsSpec(allow=["get_timeline", "merge_events"], write=["merge_events"])
    assert visible_tool_names(spec, "autonomous") == {"get_timeline", "merge_events"}


def test_proposal_hides_write_tools() -> None:
    spec = ToolsSpec(allow=["get_timeline", "merge_events"], write=["merge_events"])
    assert visible_tool_names(spec, "proposal") == {"get_timeline"}
