"""Tests for CronScheduler: job registration and dispatch (no wall-clock)."""

from __future__ import annotations

from typing import Any

import pytest

from saga_agents.triggers.base import RunRequest
from saga_agents.triggers.scheduler import CronScheduler

# ---------------------------------------------------------------------------
# Stub executor
# ---------------------------------------------------------------------------


class _StubExecutor:
    """Records all RunRequests submitted to it."""

    def __init__(self) -> None:
        self.submitted: list[RunRequest] = []

    async def submit(self, req: RunRequest) -> None:
        self.submitted.append(req)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_scheduler_registers_job() -> None:
    """Adding a cron job creates exactly one APScheduler job."""
    sched = CronScheduler(executor=_StubExecutor())  # type: ignore[arg-type]
    sched.add("event-deduplicator", "0 3 * * *")
    assert len(sched._scheduler.get_jobs()) == 1


def test_scheduler_registers_multiple_jobs() -> None:
    """Adding two distinct agents registers two jobs."""
    stub = _StubExecutor()
    sched = CronScheduler(executor=stub)  # type: ignore[arg-type]
    sched.add("agent-a", "0 1 * * *")
    sched.add("agent-b", "0 2 * * *")
    assert len(sched._scheduler.get_jobs()) == 2


@pytest.mark.asyncio
async def test_scheduler_job_fires_submit_with_correct_agent_id() -> None:
    """Manually invoking the job coroutine calls executor.submit with correct args."""
    stub = _StubExecutor()
    sched = CronScheduler(executor=stub)  # type: ignore[arg-type]
    sched.add("my-agent", "* * * * *")

    jobs = sched._scheduler.get_jobs()
    assert len(jobs) == 1

    # Invoke the registered coroutine function directly — no scheduler start needed.
    job = jobs[0]
    func: Any = job.func
    await func()

    assert len(stub.submitted) == 1
    assert stub.submitted[0].agent_id == "my-agent"
    assert stub.submitted[0].reason == "schedule"


@pytest.mark.asyncio
async def test_scheduler_late_binding_each_agent_id_correct() -> None:
    """Verify no late-binding bug: each job fires with its own agent_id."""
    stub = _StubExecutor()
    sched = CronScheduler(executor=stub)  # type: ignore[arg-type]
    sched.add("first-agent", "0 1 * * *")
    sched.add("second-agent", "0 2 * * *")

    jobs = sched._scheduler.get_jobs()
    # Fire both jobs manually
    for job in jobs:
        func: Any = job.func
        await func()

    agent_ids = {req.agent_id for req in stub.submitted}
    assert agent_ids == {"first-agent", "second-agent"}
    reasons = {req.reason for req in stub.submitted}
    assert reasons == {"schedule"}


def test_shutdown_before_start_does_not_raise() -> None:
    """Calling shutdown() before start() must not raise."""
    sched = CronScheduler(executor=_StubExecutor())  # type: ignore[arg-type]
    sched.shutdown()  # should be a no-op
