"""Factory for a coroutine that calls a named SAGA MCP tool directly.

Uses :class:`pydantic_ai.mcp.MCPServerStreamableHTTP` which exposes
``direct_call_tool(name, args)`` for one-shot calls without running a full
Pydantic AI agent loop.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic_ai.mcp import MCPServerStreamableHTTP


def build_mcp_call(
    base_url: str,
    bearer_token: str,
) -> Callable[[str, dict[str, Any]], Awaitable[Any]]:
    """Return an async callable that invokes a SAGA MCP tool by name.

    The returned coroutine opens a transient connection to the MCP server for
    each call, which is acceptable for the low-frequency approve-proposal path.

    Args:
        base_url: Full URL of the MCP server endpoint.
        bearer_token: API token sent as ``Authorization: Bearer …``.

    Returns:
        An async callable ``mcp_call(action, arguments) -> Any``.
    """

    async def mcp_call(action: str, arguments: dict[str, Any]) -> Any:  # noqa: ANN401
        server = MCPServerStreamableHTTP(
            base_url,
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
        async with server:
            result = await server.direct_call_tool(action, arguments)
        return result

    return mcp_call
