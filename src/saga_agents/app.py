"""saga-agents service bootstrap.

Exports:
- :class:`Service` — dataclass holding all assembled service objects.
- :func:`build_service` — pure wiring function (no I/O, no servers started).
- :func:`run_service` — async entry point: loads config, connects to Redis,
  starts all subsystems, and serves the FastAPI app via uvicorn.
- :func:`main` — synchronous CLI entry point (registered as the ``saga-agents``
  script in ``pyproject.toml``).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import uvicorn
from fastapi import FastAPI

from saga_agents.config.loader import load_agent_files, load_global_config
from saga_agents.config.models import AgentDefinition, GlobalConfig, ScheduleTrigger
from saga_agents.core.logging import get_logger
from saga_agents.metrics.registry import AGENT_CONCURRENCY_LIMIT
from saga_agents.proposals.store import SqliteProposalStore
from saga_agents.runtime.mcp_call import build_mcp_call
from saga_agents.runtime.runner import AgentRunner
from saga_agents.tracing.langfuse import configure_tracing
from saga_agents.triggers.api import build_api
from saga_agents.triggers.executor import RunExecutor
from saga_agents.triggers.redis_listener import RedisListener
from saga_agents.triggers.scheduler import CronScheduler

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Service dataclass
# ---------------------------------------------------------------------------


@dataclass
class Service:
    """Container for all assembled service objects.

    Args:
        runner: The :class:`AgentRunner` that executes agent runs.
        executor: The :class:`RunExecutor` that dispatches runs with concurrency limits.
        scheduler: The :class:`CronScheduler` with all schedule triggers registered.
        listener: The :class:`RedisListener` for event-triggered runs (``None`` when
            Redis is not configured).
        api: The :class:`FastAPI` application for the external trigger API.
    """

    runner: AgentRunner
    executor: RunExecutor
    scheduler: CronScheduler
    listener: RedisListener | None
    api: FastAPI = field(repr=False)


# ---------------------------------------------------------------------------
# Pure wiring
# ---------------------------------------------------------------------------


def build_service(
    config: GlobalConfig,
    definitions: list[AgentDefinition],
    *,
    redis: Any | None = None,  # noqa: ANN401
    proposal_store: SqliteProposalStore | None = None,
    mcp_call: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
) -> Service:
    """Assemble all service objects from the supplied configuration.

    No network connections are opened; no background tasks are started.  This
    makes the function safe to call in tests without any running event loop or
    external infrastructure.

    Args:
        config: Validated global configuration.
        definitions: List of :class:`AgentDefinition` instances to wire up.
        redis: Optional ``redis.asyncio`` client.  When provided, the
            :class:`RedisListener` and the advisory run-lock in
            :class:`RunExecutor` are enabled.
        proposal_store: Optional :class:`SqliteProposalStore` to persist
            proposals produced by agents in ``proposal`` autonomy mode.
        mcp_call: Optional coroutine factory passed to
            :func:`~saga_agents.triggers.api.build_api` for the approve
            endpoint.

    Returns:
        A fully wired :class:`Service` instance.
    """
    # Only wire enabled agents.
    definitions_by_id: dict[str, AgentDefinition] = {d.id: d for d in definitions if d.enabled}

    # Build core runtime objects.
    runner = AgentRunner(config, proposal_sink=proposal_store)
    executor = RunExecutor(
        runner,
        definitions_by_id,
        global_limit=config.runtime.max_concurrent_runs_global,
        redis=redis,
    )
    AGENT_CONCURRENCY_LIMIT.set(config.runtime.max_concurrent_runs_global)

    # Register all schedule triggers.
    scheduler = CronScheduler(executor)
    for definition in definitions_by_id.values():
        for trigger in definition.triggers:
            if isinstance(trigger, ScheduleTrigger):
                scheduler.add(definition.id, trigger.cron)

    # Build Redis listener (only when Redis is available).
    listener: RedisListener | None = None
    if redis is not None:
        listener = RedisListener(
            redis,
            config.redis.event_channel,
            definitions_by_id,
            executor,
        )

    # Read the external API token from the environment.
    external_token = os.environ.get("AGENTS_EXTERNAL_TOKEN", "changeme")
    if not external_token or external_token == "changeme":
        log.warning(
            "external_trigger_token_insecure",
            hint="Set AGENTS_EXTERNAL_TOKEN to a strong secret before exposing this service.",
        )

    # Build FastAPI app.
    api = build_api(
        executor,
        definitions_by_id,
        expected_token=external_token,
        proposal_store=proposal_store,
        mcp_call=mcp_call,
    )

    return Service(
        runner=runner,
        executor=executor,
        scheduler=scheduler,
        listener=listener,
        api=api,
    )


# ---------------------------------------------------------------------------
# Async service runner
# ---------------------------------------------------------------------------


async def run_service(config_path: str) -> None:
    """Load config and run all saga-agents subsystems until interrupted.

    Starts the scheduler, Redis listener, and uvicorn in the current event
    loop.  Performs a graceful shutdown (listener stop, scheduler shutdown,
    Redis close) in the ``finally`` block.

    Args:
        config_path: File-system path to the global YAML config file.
    """
    # Load configuration.
    config = load_global_config(config_path)
    definitions = load_agent_files(config.agents_dir)

    # Configure tracing (no-op when Langfuse keys are absent).
    configure_tracing(config.langfuse)

    # Connect to Redis.
    import redis.asyncio as aioredis  # local import to keep module top-level clean

    redis_client = aioredis.from_url(config.redis.url)

    # Verify Redis is reachable at startup (non-fatal — schedule/external triggers still work).
    try:
        await redis_client.ping()
    except Exception as exc:  # noqa: BLE001
        log.warning("redis_ping_failed", error=str(exc), hint="Event triggers will not fire.")

    # Initialise proposal store.
    proposal_store = SqliteProposalStore(config.runtime.proposals_db)
    await proposal_store.init()

    # Build the real MCP-call coroutine.
    mcp_call = build_mcp_call(config.mcp.base_url, config.mcp.bearer_token)

    # Wire everything together.
    service = build_service(
        config,
        definitions,
        redis=redis_client,
        proposal_store=proposal_store,
        mcp_call=mcp_call,
    )

    # Start background subsystems.
    service.scheduler.start()

    listener_task: asyncio.Task[None] | None = None
    if service.listener is not None:
        listener_task = asyncio.create_task(service.listener.run())

    # Serve the FastAPI app.
    uv_config = uvicorn.Config(
        service.api,
        host="0.0.0.0",  # noqa: S104
        port=int(os.environ.get("AGENTS_PORT", "8099")),
        log_level="info",
    )
    server = uvicorn.Server(uv_config)

    try:
        await server.serve()
    finally:
        log.info("saga_agents_shutting_down")

        if service.listener is not None:
            await service.listener.stop()

        if listener_task is not None and not listener_task.done():
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass

        service.scheduler.shutdown()

        try:
            await redis_client.aclose()
        except Exception as exc:  # noqa: BLE001
            log.warning("redis_close_error", error=str(exc))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Synchronous entry point registered as the ``saga-agents`` console script."""
    config_path = os.environ.get("SAGA_AGENTS_CONFIG", "config/agents.yaml")
    asyncio.run(run_service(config_path))
