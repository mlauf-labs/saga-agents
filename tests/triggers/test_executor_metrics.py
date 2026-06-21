"""Tests for RunExecutor metric instrumentation (Task 14)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from prometheus_client import generate_latest

from saga_agents.config.models import AgentDefinition, Limits
from saga_agents.metrics.registry import AGENT_REGISTRY
from saga_agents.runtime.report import RunReport, RunStatus
from saga_agents.triggers.base import RunRequest
from saga_agents.triggers.executor import RunExecutor


def _make_definition(agent_id: str) -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        enabled=True,
        limits=Limits(max_concurrent_runs=1, timeout_seconds=30),
    )


def _ok_report(agent_id: str) -> RunReport:
    return RunReport(
        run_id="test-run-id",
        agent_id=agent_id,
        status=RunStatus.OK,
        summary="done",
        tool_calls=0,
        proposals=[],
        error=None,
        trace_id=None,
    )


async def test_submit_records_run_metric() -> None:
    """A successful submit increments saga_agent_runs_total with result=ok."""
    defn = _make_definition("agent-x")
    runner = AsyncMock()
    runner.run = AsyncMock(return_value=_ok_report("agent-x"))

    ex = RunExecutor(runner, {"agent-x": defn}, global_limit=2)
    await ex.submit(RunRequest(agent_id="agent-x", reason="schedule"))

    text = generate_latest(AGENT_REGISTRY).decode()
    assert 'saga_agent_runs_total{agent_id="agent-x",result="ok",trigger="schedule"}' in text


async def test_submit_error_result_records_error_metric() -> None:
    """A run that returns RunStatus.ERROR increments saga_agent_runs_total with result=error."""
    defn = _make_definition("agent-y")
    runner = AsyncMock()
    runner.run = AsyncMock(
        return_value=RunReport(
            run_id="r",
            agent_id="agent-y",
            status=RunStatus.ERROR,
            summary="",
            tool_calls=0,
            proposals=[],
            error="oops",
            trace_id=None,
        )
    )

    ex = RunExecutor(runner, {"agent-y": defn}, global_limit=2)
    await ex.submit(RunRequest(agent_id="agent-y", reason="event"))

    text = generate_latest(AGENT_REGISTRY).decode()
    assert 'saga_agent_runs_total{agent_id="agent-y",result="error",trigger="event"}' in text


async def test_submit_exception_records_error_metric() -> None:
    """Unexpected runner exception increments saga_agent_runs_total with result=error."""
    defn = _make_definition("agent-z")
    runner = AsyncMock()
    runner.run = AsyncMock(side_effect=RuntimeError("boom"))

    ex = RunExecutor(runner, {"agent-z": defn}, global_limit=2)
    await ex.submit(RunRequest(agent_id="agent-z", reason="manual"))

    text = generate_latest(AGENT_REGISTRY).decode()
    assert 'saga_agent_runs_total{agent_id="agent-z",result="error",trigger="manual"}' in text
