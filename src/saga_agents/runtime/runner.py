"""AgentRunner: builds a Pydantic AI agent from an AgentDefinition and runs it."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Protocol

from pydantic_ai import Agent
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.usage import UsageLimits

from saga_agents.config.models import AgentDefinition, GlobalConfig
from saga_agents.runtime.model import build_model
from saga_agents.runtime.propose import build_propose_tool
from saga_agents.runtime.report import RunDeps, RunReport, RunStatus
from saga_agents.runtime.toolset import build_mcp_server, filtered_server, visible_tool_names


def get_logger(name: str) -> logging.Logger:
    """Return a stdlib logger for *name*."""
    return logging.getLogger(name)


log = get_logger("saga_agents.runtime.runner")
logger = log  # keep module-level ``logger`` alias for existing callers


class ProposalSink(Protocol):
    """Persistence target for proposed actions (Task 13 will provide a concrete impl)."""

    async def add(
        self,
        agent_id: str,
        run_id: str,
        action: str,
        arguments: dict[str, Any],
        rationale: str,
    ) -> object: ...


def _count_tool_calls(result: Any) -> int:
    """Count non-``propose`` ToolCallPart entries across all messages.

    Args:
        result: The :class:`AgentRunResult` returned by ``agent.run``.

    Returns:
        Number of MCP/function tool calls (``propose`` excluded).
    """
    count = 0
    try:
        for message in result.all_messages():
            parts = getattr(message, "parts", [])
            for part in parts:
                if isinstance(part, ToolCallPart):
                    name = getattr(part, "tool_name", None)
                    if name != "propose":
                        count += 1
    except Exception as exc:  # noqa: BLE001
        log.warning("count_tool_calls_failed error=%s", exc)
    return count


class AgentRunner:
    """Builds a Pydantic AI agent from an :class:`AgentDefinition` and runs it."""

    def __init__(
        self,
        config: GlobalConfig,
        *,
        proposal_sink: ProposalSink | None = None,
        mcp_server_factory: Callable[[str, str], Any] = build_mcp_server,
        model_factory: Callable[[str, str], Any] = build_model,
    ) -> None:
        self._config = config
        self._proposal_sink = proposal_sink
        self._mcp_server_factory = mcp_server_factory
        self._model_factory = model_factory

    async def run(
        self,
        definition: AgentDefinition,
        *,
        prompt: str | None = None,
    ) -> RunReport:
        """Build and run an agent for *definition*, returning a :class:`RunReport`.

        Never raises — all exceptions are caught and reflected in the report status.

        Args:
            definition: The agent to run.
            prompt: Optional user prompt; defaults to ``"Run your maintenance task now."``.

        Returns:
            A :class:`RunReport` describing the outcome.
        """
        # 1. Resolve model
        model_name = definition.model or self._config.ollama.default_model
        model = self._model_factory(self._config.ollama.base_url, model_name)

        # 2. Build filtered toolset
        server = self._mcp_server_factory(self._config.mcp.base_url, self._config.mcp.bearer_token)
        allowed = visible_tool_names(definition.tools, definition.autonomy)
        toolset = filtered_server(server, allowed)

        # 3. Build agent
        is_proposal_mode = definition.autonomy == "proposal"
        extra_tools = [build_propose_tool()] if is_proposal_mode else []

        agent: Agent[RunDeps, str] = Agent(
            model,
            instructions=definition.system_prompt,
            toolsets=[toolset],
            tools=extra_tools,
            output_type=str,
            deps_type=RunDeps,
        )

        # 4. Create run context
        run_id = uuid.uuid4().hex
        deps = RunDeps(run_id=run_id, agent_id=definition.id, proposals=[])

        # 5. Resolve prompt
        effective_prompt = prompt if prompt is not None else "Run your maintenance task now."

        # 6. Run with limits + timeout
        limits = definition.limits
        status: RunStatus
        summary: str
        tool_calls: int
        error: str | None

        try:
            async with asyncio.timeout(limits.timeout_seconds):
                async with agent:
                    result = await agent.run(
                        effective_prompt,
                        deps=deps,
                        usage_limits=UsageLimits(
                            request_limit=limits.max_steps,
                            tool_calls_limit=limits.max_tool_calls,
                        ),
                    )
            status = RunStatus.OK
            summary = str(result.output)
            tool_calls = _count_tool_calls(result)
            error = None
        except UsageLimitExceeded as exc:
            # tool_calls=0: result was never assigned, so no reliable count is available
            status, summary, tool_calls, error = RunStatus.LIMIT_EXCEEDED, "", 0, str(exc)
        except TimeoutError:
            # tool_calls=0: result was never assigned, so no reliable count is available
            status, summary, tool_calls, error = (
                RunStatus.TIMEOUT,
                "",
                0,
                f"Run exceeded {limits.timeout_seconds}s",
            )
        except Exception as exc:  # noqa: BLE001
            # tool_calls=0: result was never assigned, so no reliable count is available
            status, summary, tool_calls, error = RunStatus.ERROR, "", 0, str(exc)

        # 7. Persist proposals (proposal mode only)
        persistence_error: str | None = None
        if is_proposal_mode and self._proposal_sink is not None:
            for p in deps.proposals:
                try:
                    await self._proposal_sink.add(
                        agent_id=definition.id,
                        run_id=run_id,
                        action=p.action,
                        arguments=p.arguments,
                        rationale=p.rationale,
                    )
                except Exception as sink_exc:  # noqa: BLE001
                    persistence_error = str(sink_exc)
                    logger.warning(
                        "ProposalSink.add failed for run %s: %s",
                        run_id,
                        sink_exc,
                    )

        # Surface persistence degradation in the summary so callers see it
        # without changing status/error semantics.
        if persistence_error is not None and status == RunStatus.OK:
            summary = f"{summary}\n[warning: proposal persistence degraded: {persistence_error}]"

        # 8. Return report
        return RunReport(
            run_id=run_id,
            agent_id=definition.id,
            status=status,
            summary=summary,
            tool_calls=tool_calls,
            proposals=list(deps.proposals),
            error=error,
            trace_id=None,
        )
