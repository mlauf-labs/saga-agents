"""Tests for AgentRunner."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.toolsets.filtered import FilteredToolset

from saga_agents.config.models import AgentDefinition, GlobalConfig
from saga_agents.runtime.report import RunStatus
from saga_agents.runtime.runner import AgentRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _EmptyToolset(FunctionToolset[None]):
    """An empty FunctionToolset whose .filtered() returns itself unchanged."""

    def filtered(self, fn: Any) -> FilteredToolset[Any]:
        return super().filtered(fn)


def _empty_toolset_factory(*args: Any, **kwargs: Any) -> _EmptyToolset:
    return _EmptyToolset()


class FakeSink:
    """Records ProposalSink.add() calls for assertions."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def add(
        self,
        agent_id: str,
        run_id: str,
        action: str,
        arguments: dict[str, Any],
        rationale: str,
    ) -> object:
        self.calls.append(
            {
                "agent_id": agent_id,
                "run_id": run_id,
                "action": action,
                "arguments": arguments,
                "rationale": rationale,
            }
        )
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_returns_ok_report(
    global_config: GlobalConfig,
    demo_definition: AgentDefinition,
) -> None:
    """A TestModel run should produce an OK RunReport with no proposals."""
    runner = AgentRunner(
        global_config,
        mcp_server_factory=_empty_toolset_factory,
        model_factory=lambda *a, **k: TestModel(),
    )
    report = await runner.run(demo_definition)

    assert report.status == RunStatus.OK
    assert report.agent_id == demo_definition.id
    assert report.proposals == []
    assert report.error is None
    assert report.run_id != ""


@pytest.mark.asyncio
async def test_runner_error_status(
    global_config: GlobalConfig,
    demo_definition: AgentDefinition,
) -> None:
    """A FunctionModel that raises should produce an ERROR report — never raise out."""

    def boom(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise RuntimeError("model exploded")

    runner = AgentRunner(
        global_config,
        mcp_server_factory=_empty_toolset_factory,
        model_factory=lambda *a, **k: FunctionModel(boom),
    )
    report = await runner.run(demo_definition)

    assert report.status == RunStatus.ERROR
    assert "model exploded" in (report.error or "")
    assert report.summary == ""


@pytest.mark.asyncio
async def test_runner_proposal_mode_persists(
    global_config: GlobalConfig,
    proposal_definition: AgentDefinition,
) -> None:
    """Proposal-mode run: propose tool is called, sink.add is invoked, proposals in report."""
    call_count: dict[str, int] = {"n": 0}

    def proposal_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="propose",
                        args={
                            "action": "delete_doc",
                            "arguments": {"doc_id": "abc"},
                            "rationale": "document is stale",
                        },
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content="proposals submitted")])

    sink = FakeSink()
    runner = AgentRunner(
        global_config,
        proposal_sink=sink,
        mcp_server_factory=_empty_toolset_factory,
        model_factory=lambda *a, **k: FunctionModel(proposal_fn),
    )
    report = await runner.run(proposal_definition)

    # Report should be OK with one proposal
    assert report.status == RunStatus.OK
    assert len(report.proposals) == 1
    assert report.proposals[0].action == "delete_doc"
    assert report.proposals[0].arguments == {"doc_id": "abc"}
    assert report.proposals[0].rationale == "document is stale"

    # Sink should have been called once
    assert len(sink.calls) == 1
    assert sink.calls[0]["agent_id"] == proposal_definition.id
    assert sink.calls[0]["action"] == "delete_doc"
