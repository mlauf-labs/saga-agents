"""Generic ``propose`` tool for proposal-mode agents."""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext, Tool

from saga_agents.runtime.report import ProposedAction, RunDeps


def _propose(
    ctx: RunContext[RunDeps],
    action: str,
    arguments: dict[str, Any],
    rationale: str,
) -> str:
    """Append a proposed action to the run's proposal list.

    Args:
        ctx: The active run context carrying :class:`RunDeps`.
        action: The name of the action being proposed.
        arguments: Key/value arguments for the action.
        rationale: Human-readable justification for the proposal.

    Returns:
        A confirmation string for the model.
    """
    ctx.deps.proposals.append(
        ProposedAction(action=action, arguments=arguments, rationale=rationale)
    )
    return f"Proposal recorded: {action}"


def build_propose_tool() -> Tool[RunDeps]:
    """Build and return the ``propose`` :class:`Tool`.

    Returns:
        A :class:`Tool` wrapping the ``propose`` function.
    """
    return Tool(_propose, name="propose")
