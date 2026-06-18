"""Proposal apply: invoke the MCP tool named in a ProposalRecord."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from saga_agents.proposals.store import ProposalRecord


async def apply_proposal(
    record: ProposalRecord,
    mcp_call: Callable[[str, dict[str, Any]], Awaitable[Any]],
) -> Any:
    """Apply a proposal by invoking *mcp_call* with the recorded action and arguments.

    This is pure indirection: the caller injects the real MCP client (or a test fake).

    Args:
        record: The :class:`ProposalRecord` to apply.
        mcp_call: Coroutine that takes ``(action: str, arguments: dict)`` and returns the
            result of the MCP tool invocation.

    Returns:
        Whatever *mcp_call* returns.
    """
    return await mcp_call(record.action, record.arguments)
