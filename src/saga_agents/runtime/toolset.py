"""MCP server factory and tool allow-list filtering."""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import FilteredToolset

from saga_agents.config.models import ToolsSpec


def build_mcp_server(base_url: str, bearer_token: str) -> MCPServerStreamableHTTP:
    """Create an :class:`MCPServerStreamableHTTP` with a Bearer auth header.

    Args:
        base_url: Full URL of the MCP server endpoint.
        bearer_token: API token to send as ``Authorization: Bearer …``.

    Returns:
        A configured :class:`MCPServerStreamableHTTP` instance.
    """
    return MCPServerStreamableHTTP(
        base_url,
        headers={"Authorization": f"Bearer {bearer_token}"},
    )


def visible_tool_names(tools: ToolsSpec, autonomy: str) -> set[str]:
    """Compute the set of tool names visible to an agent.

    - ``"autonomous"`` mode: all allowed tools are visible.
    - Any other autonomy (e.g. ``"proposal"``): write tools are hidden.

    Args:
        tools: The :class:`ToolsSpec` from the agent definition.
        autonomy: The agent's autonomy level string.

    Returns:
        Set of tool names the agent may see/call.
    """
    allowed = set(tools.allow)
    if autonomy == "autonomous":
        return allowed
    return allowed - set(tools.write)


def filtered_server(
    server: MCPServerStreamableHTTP,
    allowed: set[str],
) -> FilteredToolset[Any]:
    """Wrap a server in a :class:`FilteredToolset` that admits only *allowed* tools.

    Args:
        server: The MCP server to filter.
        allowed: Set of tool names to permit.

    Returns:
        A :class:`FilteredToolset` view of *server*.
    """

    def _allow(ctx: RunContext[Any], td: ToolDefinition) -> bool:
        return td.name in allowed

    return server.filtered(_allow)
