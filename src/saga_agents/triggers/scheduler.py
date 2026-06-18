"""CronScheduler: schedule agent runs via APScheduler cron expressions."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]

from saga_agents.triggers.base import RunRequest
from saga_agents.triggers.executor import RunExecutor

log = logging.getLogger(__name__)


class CronScheduler:
    """Schedules agent runs on cron expressions using APScheduler.

    Each registered agent gets a job that fires its cron schedule and submits
    a :class:`RunRequest` with ``reason="schedule"`` to the executor.
    """

    def __init__(self, executor: RunExecutor) -> None:
        self._executor = executor
        self._scheduler: AsyncIOScheduler = AsyncIOScheduler()
        self._started = False

    def add(self, agent_id: str, cron: str) -> None:
        """Register *agent_id* to be triggered on *cron* schedule.

        Args:
            agent_id: The ID of the agent to run.
            cron: A standard 5-field cron expression, e.g. ``"0 3 * * *"``.
        """

        async def _fire(aid: str = agent_id) -> None:
            log.info("cron_trigger_fired agent_id=%s", aid)
            await self._executor.submit(RunRequest(aid, reason="schedule"))

        self._scheduler.add_job(
            _fire,
            trigger=CronTrigger.from_crontab(cron),
            id=f"cron:{agent_id}",
            replace_existing=True,
        )
        log.info("cron_job_registered agent_id=%s cron=%s", agent_id, cron)

    def start(self) -> None:
        """Start the underlying APScheduler scheduler."""
        self._scheduler.start()
        self._started = True
        log.info("cron_scheduler_started")

    def shutdown(self) -> None:
        """Shut down the scheduler; safe to call even if never started."""
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            log.info("cron_scheduler_stopped")
