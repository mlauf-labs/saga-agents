"""AgentRunner: builds a Pydantic AI agent from an AgentDefinition and runs it."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from opentelemetry import trace as otel_trace
from pydantic_ai import Agent
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.usage import UsageLimits

from saga_agents.config.models import AgentDefinition, GlobalConfig
from saga_agents.core.errors import GuidanceFetchError
from saga_agents.core.logging import get_logger
from saga_agents.runtime.guidance import GuidanceProvider, referenced_keys, substitute
from saga_agents.runtime.model import build_model
from saga_agents.runtime.propose import build_propose_tool
from saga_agents.runtime.report import RunDeps, RunReport, RunStatus
from saga_agents.runtime.toolset import build_mcp_server, filtered_server, visible_tool_names

log = get_logger(__name__)
logger = log  # keep module-level ``logger`` alias for existing callers

_tracer = otel_trace.get_tracer(__name__)


def current_trace_id() -> str | None:
    """Return the active OpenTelemetry trace id as a 32-char hex string, or None.

    Returns None when no valid recording span is active — i.e. when Langfuse/OTel
    tracing is disabled (the no-op tracer yields an invalid span context).
    """
    ctx = otel_trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


class GuidanceLike(Protocol):
    """Minimal protocol satisfied by :class:`GuidanceProvider` and test fakes."""

    async def get(self) -> dict[str, str]: ...


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


def _count_tool_calls(result: Any) -> int:  # noqa: ANN401
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
    except Exception as exc:
        log.warning("count_tool_calls_failed", error=str(exc))
    return count


class AgentRunner:
    """Builds a Pydantic AI agent from an :class:`AgentDefinition` and runs it."""

    def __init__(
        self,
        config: GlobalConfig,
        *,
        proposal_sink: ProposalSink | None = None,
        guidance_provider: GuidanceLike | None = None,
        mcp_server_factory: Callable[[str, str], Any] = build_mcp_server,
        model_factory: Callable[[str, str], Any] = build_model,
    ) -> None:
        self._config = config
        self._proposal_sink = proposal_sink
        self._mcp_server_factory = mcp_server_factory
        self._model_factory = model_factory
        self._guidance: GuidanceLike = guidance_provider or GuidanceProvider(
            self._mcp_server_factory,
            config.mcp.base_url,
            config.mcp.bearer_token,
            ttl_seconds=config.runtime.guidance_cache_ttl_seconds,
        )

    async def _resolve_system_prompt(self, definition: AgentDefinition) -> str:
        """Return the system prompt with all ``{{saga.*}}`` placeholders substituted.

        If the prompt contains no saga placeholders the guidance provider is not
        called and the original prompt is returned unchanged.

        Args:
            definition: The agent whose ``system_prompt`` to resolve.

        Returns:
            The resolved system prompt string.

        Raises:
            GuidanceFetchError: If the guidance provider fails and the prompt
                contains at least one saga placeholder.
        """
        if not referenced_keys(definition.system_prompt):
            return definition.system_prompt
        guidance = await self._guidance.get()
        return substitute(definition.system_prompt, guidance)

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

        # 3. Resolve system prompt (substitute {{saga.*}} placeholders)
        run_id = uuid.uuid4().hex
        try:
            system_prompt = await self._resolve_system_prompt(definition)
        except GuidanceFetchError as exc:
            return RunReport(
                run_id=run_id,
                agent_id=definition.id,
                status=RunStatus.ERROR,
                summary="",
                tool_calls=0,
                proposals=[],
                error=str(exc),
            )

        # 4. Build agent
        is_proposal_mode = definition.autonomy == "proposal"
        extra_tools = [build_propose_tool()] if is_proposal_mode else []

        agent: Agent[RunDeps, str] = Agent(
            model,
            instructions=system_prompt,
            toolsets=[toolset],
            tools=extra_tools,
            output_type=str,
            deps_type=RunDeps,
        )

        # 5. Create run context (run_id already generated above)
        deps = RunDeps(run_id=run_id, agent_id=definition.id, proposals=[])

        # 6. Resolve prompt
        effective_prompt = prompt if prompt is not None else "Run your maintenance task now."

        # 7. Run with limits + timeout
        limits = definition.limits
        status: RunStatus
        summary: str
        tool_calls: int
        error: str | None

        trace_id: str | None = None
        try:
            # Wrap the run in a named span so Langfuse gets a clean root and we can
            # capture the trace id to link the run report back to the trace.
            with _tracer.start_as_current_span("saga_agent_run") as span:
                span.set_attribute("saga.agent_id", definition.id)
                span.set_attribute("saga.run_id", run_id)
                trace_id = current_trace_id()
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
        except Exception as exc:
            # tool_calls=0: result was never assigned, so no reliable count is available
            status, summary, tool_calls, error = RunStatus.ERROR, "", 0, str(exc)

        # 8. Persist proposals (proposal mode only)
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
                except Exception as sink_exc:
                    persistence_error = str(sink_exc)
                    logger.warning(
                        "proposal_sink_add_failed",
                        run_id=run_id,
                        error=str(sink_exc),
                    )

        # Surface persistence degradation in the summary so callers see it
        # without changing status/error semantics.
        if persistence_error is not None and status == RunStatus.OK:
            summary = f"{summary}\n[warning: proposal persistence degraded: {persistence_error}]"

        # 9. Return report
        return RunReport(
            run_id=run_id,
            agent_id=definition.id,
            status=status,
            summary=summary,
            tool_calls=tool_calls,
            proposals=list(deps.proposals),
            error=error,
            trace_id=trace_id,
        )
