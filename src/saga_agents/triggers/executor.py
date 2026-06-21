"""RunExecutor: concurrency-limited agent run dispatcher."""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import Any

from saga_agents.config.models import AgentDefinition
from saga_agents.core.logging import get_logger
from saga_agents.metrics.registry import AGENT_INFLIGHT, AGENT_RUN_DURATION, AGENT_RUNS
from saga_agents.runtime.report import RunStatus
from saga_agents.runtime.runner import AgentRunner
from saga_agents.triggers.base import RunRequest

log = get_logger(__name__)

# Lua script for ownership-guarded compare-and-delete.
# Deletes the key only when its value matches the caller's token.
_LUA_COMPARE_AND_DELETE = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) "
    "else return 0 end"
)


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
                "submit_skipped_unknown_or_disabled",
                agent_id=req.agent_id,
                reason=req.reason,
                known=definition is not None,
                enabled=definition.enabled if definition is not None else False,
            )
            return

        agent_id = req.agent_id
        lock_key = f"agent:lock:{agent_id}"
        lock_token: str | None = None

        async with self._global_sem, self._agent_sems[agent_id]:
            # Optional Redis advisory lock (cross-process deduplication).
            if self._redis is not None:
                lock_token = uuid.uuid4().hex
                acquired: Any = await self._redis.set(
                    lock_key,
                    lock_token,
                    nx=True,
                    ex=definition.limits.timeout_seconds,
                )
                if not acquired:
                    log.warning(
                        "submit_skipped_redis_lock",
                        agent_id=agent_id,
                        reason=req.reason,
                    )
                    return

            AGENT_INFLIGHT.inc()
            _start = time.perf_counter()
            try:
                report = await self._runner.run(definition)
            except Exception as exc:
                AGENT_RUNS.labels(agent_id=agent_id, trigger=req.reason, result="error").inc()
                log.error(
                    "run_unexpected_exception",
                    agent_id=agent_id,
                    reason=req.reason,
                    error=str(exc),
                )
                return
            finally:
                AGENT_RUN_DURATION.labels(agent_id=agent_id).observe(time.perf_counter() - _start)
                AGENT_INFLIGHT.dec()
                if self._redis is not None and lock_token is not None:
                    # best-effort release
                    with contextlib.suppress(Exception):
                        await self._redis.eval(_LUA_COMPARE_AND_DELETE, 1, lock_key, lock_token)

            result = "ok" if report.status == RunStatus.OK else "error"
            AGENT_RUNS.labels(agent_id=agent_id, trigger=req.reason, result=result).inc()

            # Surface the failure reason: a non-OK run logs at warning level WITH the
            # error, so debugging never requires reproducing the run.
            log_fn = log.info if report.status == RunStatus.OK else log.warning
            log_fn(
                "run_completed",
                agent_id=agent_id,
                reason=req.reason,
                status=report.status,
                tool_calls=report.tool_calls,
                proposals=len(report.proposals),
                trace_id=report.trace_id,
                error=report.error,
            )
