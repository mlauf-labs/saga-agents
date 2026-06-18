"""Runtime data models: RunStatus, ProposedAction, RunDeps, RunReport."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RunStatus(StrEnum):
    """Terminal status of a single agent run."""

    OK = "ok"
    LIMIT_EXCEEDED = "limit_exceeded"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class ProposedAction:
    """A single action proposed by the agent in proposal-mode."""

    action: str
    arguments: dict[str, Any]
    rationale: str


@dataclass
class RunDeps:
    """Dependencies injected into every agent run.

    ``proposals`` is a mutable list that the ``propose`` tool appends to during
    proposal-mode runs.
    """

    run_id: str
    agent_id: str
    proposals: list[ProposedAction] = field(default_factory=list)


@dataclass
class RunReport:
    """Summary produced at the end of an agent run."""

    run_id: str
    agent_id: str
    status: RunStatus
    summary: str
    tool_calls: int
    proposals: list[ProposedAction]
    error: str | None = None
    trace_id: str | None = None
