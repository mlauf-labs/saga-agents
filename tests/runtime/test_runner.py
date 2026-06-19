"""Tests for AgentRunner."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.toolsets.filtered import FilteredToolset

from saga_agents.config.models import AgentDefinition, GlobalConfig, ToolsSpec
from saga_agents.core.errors import GuidanceFetchError
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


# ---------------------------------------------------------------------------
# Guidance provider helpers
# ---------------------------------------------------------------------------


class _FakeGuidance:
    def __init__(self, result: Any) -> None:
        self._result = result
        self.calls = 0

    async def get(self) -> dict[str, str]:
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result  # type: ignore[no-any-return]


def _definition_with_prompt(text: str) -> AgentDefinition:
    """Build an AgentDefinition with the given system_prompt."""
    return AgentDefinition(
        id="placeholder-agent",
        enabled=True,
        description="Test agent",
        model=None,
        autonomy="autonomous",
        tools=ToolsSpec(allow=[], write=[]),
        system_prompt=text,
    )


class FailingSink:
    """ProposalSink whose add() always raises, to test degradation surfacing."""

    async def add(
        self,
        agent_id: str,
        run_id: str,
        action: str,
        arguments: dict[str, Any],
        rationale: str,
    ) -> object:
        raise RuntimeError("db unavailable")


@pytest.mark.asyncio
async def test_runner_proposal_sink_failure_surfaces_in_summary(
    global_config: GlobalConfig,
    proposal_definition: AgentDefinition,
) -> None:
    """Proposal-mode run where sink.add raises: status stays OK, summary contains degradation note."""
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
                            "arguments": {"doc_id": "xyz"},
                            "rationale": "outdated document",
                        },
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content="proposals submitted")])

    runner = AgentRunner(
        global_config,
        proposal_sink=FailingSink(),
        mcp_server_factory=_empty_toolset_factory,
        model_factory=lambda *a, **k: FunctionModel(proposal_fn),
    )
    report = await runner.run(proposal_definition)

    # Must not raise; status stays OK despite sink failure
    assert report.status == RunStatus.OK
    assert report.error is None
    # Degradation note must appear in summary
    assert "persistence degraded" in report.summary


# ---------------------------------------------------------------------------
# Guidance / placeholder tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_system_prompt_substitutes(global_config: GlobalConfig) -> None:
    """_resolve_system_prompt replaces {{saga.store_description}} from the fake provider."""
    g = _FakeGuidance(
        {
            "store_description": "FamArchive",
            "folder_instructions": "",
            "doctype_instructions": "",
            "metadata_instructions": "",
            "summary_instructions": "",
            "language": "English",
        }
    )
    runner = AgentRunner(
        global_config,
        guidance_provider=g,
        mcp_server_factory=lambda *a, **k: _EmptyToolset(),
        model_factory=lambda *a, **k: TestModel(),
    )
    definition = _definition_with_prompt("Archive: {{saga.store_description}}.")
    out = await runner._resolve_system_prompt(definition)
    assert out == "Archive: FamArchive."
    assert g.calls == 1


@pytest.mark.asyncio
async def test_resolve_system_prompt_skips_fetch_when_no_placeholders(
    global_config: GlobalConfig,
) -> None:
    """_resolve_system_prompt does NOT call the provider when there are no placeholders."""
    g = _FakeGuidance({})
    runner = AgentRunner(
        global_config,
        guidance_provider=g,
        mcp_server_factory=lambda *a, **k: _EmptyToolset(),
        model_factory=lambda *a, **k: TestModel(),
    )
    out = await runner._resolve_system_prompt(_definition_with_prompt("no tokens"))
    assert out == "no tokens"
    assert g.calls == 0


@pytest.mark.asyncio
async def test_run_errors_when_guidance_fetch_fails(global_config: GlobalConfig) -> None:
    """run() with a failing guidance provider returns an ERROR report — never raises."""
    # Use the real production error message GuidanceProvider emits, so the assertion
    # verifies that str(exc) actually propagates into report.error (not a tautology).
    g = _FakeGuidance(
        GuidanceFetchError("Could not fetch get_store_guidance from MCP: connection refused")
    )
    runner = AgentRunner(
        global_config,
        guidance_provider=g,
        mcp_server_factory=lambda *a, **k: _EmptyToolset(),
        model_factory=lambda *a, **k: TestModel(),
    )
    report = await runner.run(_definition_with_prompt("Need {{saga.store_description}}"))
    assert report.status == RunStatus.ERROR
    assert "get_store_guidance" in (report.error or "")


def test_current_trace_id_is_none_outside_a_span() -> None:
    from saga_agents.runtime.runner import current_trace_id

    # No active recording span (tracing effectively off) → no trace id.
    assert current_trace_id() is None


def test_current_trace_id_is_hex_inside_a_span() -> None:
    from opentelemetry.sdk.trace import TracerProvider

    from saga_agents.runtime.runner import current_trace_id

    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("x"):
        tid = current_trace_id()
    assert tid is not None
    assert len(tid) == 32
    assert all(c in "0123456789abcdef" for c in tid)
