"""Tests for the propose tool."""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from saga_agents.runtime.propose import build_propose_tool
from saga_agents.runtime.report import ProposedAction, RunDeps


def test_propose_appends_to_deps() -> None:
    deps = RunDeps(run_id="r1", agent_id="a1", proposals=[])
    # A placeholder model name is required even when using override(model=...)
    agent: Agent[RunDeps, str] = Agent(
        model="test",
        deps_type=RunDeps,
        tools=[build_propose_tool()],
    )

    calls: dict[str, int] = {"n": 0}

    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        if calls["n"] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="propose",
                        args={
                            "action": "merge_events",
                            "arguments": {
                                "canonical_event_id": "c",
                                "duplicate_event_ids": ["d"],
                            },
                            "rationale": "same meeting",
                        },
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content="done")])

    with agent.override(model=FunctionModel(model_fn)):
        result = agent.run_sync("dedup please", deps=deps)

    assert result.output == "done"
    assert deps.proposals == [
        ProposedAction(
            action="merge_events",
            arguments={"canonical_event_id": "c", "duplicate_event_ids": ["d"]},
            rationale="same meeting",
        )
    ]
