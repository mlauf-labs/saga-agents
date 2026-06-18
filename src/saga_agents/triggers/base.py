"""Base data types for the trigger dispatch layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RunRequest:
    """A request to run a specific agent.

    Attributes:
        agent_id: The ID of the agent to run.
        reason: Human-readable reason for the run (e.g. ``"event:document.added"``).
        context: Optional extra context passed through to the runner.
    """

    agent_id: str
    reason: str
    context: dict[str, Any] = field(default_factory=dict)
