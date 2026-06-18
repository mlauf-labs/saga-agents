"""RunExecutor: concurrency-limited agent run dispatcher."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from saga_agents.config.models import AgentDefinition
from saga_agents.runtime.runner import AgentRunner
from saga_agents.triggers.base import RunRequest

log = logging.getLogger(__name__)


class RunExecutor:
    """Dispatches :class:`RunRequest` instances to :class:`AgentRunner` with concurrency limits.

    Two layers of concurrency control are applied:

    1. A global semaphore (``global_limit``) caps total simultaneous runs across
       all agents.
    2. A per-agent semaphore (``definition.limits.max_concurrent_runs``) caps
       simultaneous runs of the *same* agent.

    When a Redis client is provided an advisory ``SET … NX EX`` lock is used
    as a third, cross-process layer.  If the lock cannot be acquired the run is
    skipped (logged, not queued).
    """

    def __init__(
        self,
        runner: AgentRunner,
        definitions: dict[str, AgentDefinition],
        *,
        global_limit: int,
        redis: Any | None = None,  # noqa: ANN401
    ) -> None:
        self._runner = runner
        self._definitions = definitions
        self._redis = redis
        self._global_sem = asyncio.Semaphore(global_limit)
        self._agent_sems: dict[str, asyncio.Semaphore] = {
            agent_id: asyncio.Semaphore(defn.limits.max_concurrent_runs)
            for agent_id, defn in definitions.items()
        }

    async def submit(self, req: RunRequest) -> None:
        """Dispatch *req*, enforcing concurrency limits.

        Skips silently (with a warning log) when:
        - the agent ID is unknown,
        - the agent is disabled, or
        - a Redis advisory lock cannot be acquired (cross-process duplicate).

        Args:
            req: The run request to dispatch.
        """
        definition = self._definitions.get(req.agent_id)
        if definition is None or not definition.enabled:
            log.warning(
                "submit_skipped_unknown_or_disabled agent_id=%s reason=%s known=%s enabled=%s",
                req.agent_id,
                req.reason,
                definition is not None,
                definition.enabled if definition is not None else False,
            )
            return

        agent_id = req.agent_id
        lock_key = f"agent:lock:{agent_id}"

        async with self._global_sem:
            async with self._agent_sems[agent_id]:
                # Optional Redis advisory lock (cross-process deduplication).
                if self._redis is not None:
                    acquired: Any = await self._redis.set(  # noqa: ANN401
                        lock_key,
                        "1",
                        nx=True,
                        ex=definition.limits.timeout_seconds,
                    )
                    if not acquired:
                        log.warning(
                            "submit_skipped_redis_lock agent_id=%s reason=%s",
                            agent_id,
                            req.reason,
                        )
                        return

                try:
                    report = await self._runner.run(definition)
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "run_unexpected_exception agent_id=%s reason=%s error=%s",
                        agent_id,
                        req.reason,
                        exc,
                    )
                    return
                finally:
                    if self._redis is not None:
                        await self._redis.delete(lock_key)

                log.info(
                    "run_completed agent_id=%s reason=%s status=%s tool_calls=%d proposals=%d trace_id=%s",
                    agent_id,
                    req.reason,
                    report.status,
                    report.tool_calls,
                    len(report.proposals),
                    report.trace_id,
                )
