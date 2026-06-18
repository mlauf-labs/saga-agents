"""Tests for RunExecutor: submit dispatch, skip-unknown, skip-disabled, concurrency cap."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from saga_agents.config.models import AgentDefinition, Limits, ToolsSpec
from saga_agents.runtime.report import RunReport, RunStatus
from saga_agents.triggers.base import RunRequest
from saga_agents.triggers.executor import RunExecutor


# ---------------------------------------------------------------------------
# Fixtures and stubs
# ---------------------------------------------------------------------------


def _make_definition(
    agent_id: str,
    *,
    enabled: bool = True,
    max_concurrent_runs: int = 2,
    timeout_seconds: int = 30,
) -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        enabled=enabled,
        description="test agent",
        model=None,
        autonomy="autonomous",
        tools=ToolsSpec(),
        limits=Limits(
            max_concurrent_runs=max_concurrent_runs,
            timeout_seconds=timeout_seconds,
        ),
        system_prompt="",
    )


def _canned_report(agent_id: str) -> RunReport:
    return RunReport(
        run_id="test-run-id",
        agent_id=agent_id,
        status=RunStatus.OK,
        summary="done",
        tool_calls=1,
        proposals=[],
        error=None,
        trace_id=None,
    )


class StubRunner:
    """Records which agent IDs were run and returns a canned RunReport."""

    def __init__(self) -> None:
        self.called: list[str] = []

    async def run(
        self,
        definition: AgentDefinition,
        *,
        prompt: str | None = None,
    ) -> RunReport:
        self.called.append(definition.id)
        return _canned_report(definition.id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_known_enabled_agent_calls_runner() -> None:
    """Submitting a known, enabled agent causes runner.run to be called once."""
    defn = _make_definition("agent-a")
    stub = StubRunner()
    executor = RunExecutor(
        stub,  # type: ignore[arg-type]
        {"agent-a": defn},
        global_limit=2,
    )

    await executor.submit(RunRequest(agent_id="agent-a", reason="test"))

    assert stub.called == ["agent-a"]


@pytest.mark.asyncio
async def test_submit_unknown_agent_skips_run() -> None:
    """Submitting an unknown agent ID does not call runner.run."""
    stub = StubRunner()
    executor = RunExecutor(
        stub,  # type: ignore[arg-type]
        {},
        global_limit=2,
    )

    await executor.submit(RunRequest(agent_id="ghost-agent", reason="test"))

    assert stub.called == []


@pytest.mark.asyncio
async def test_submit_disabled_agent_skips_run() -> None:
    """Submitting a disabled agent does not call runner.run."""
    defn = _make_definition("agent-b", enabled=False)
    stub = StubRunner()
    executor = RunExecutor(
        stub,  # type: ignore[arg-type]
        {"agent-b": defn},
        global_limit=2,
    )

    await executor.submit(RunRequest(agent_id="agent-b", reason="test"))

    assert stub.called == []


@pytest.mark.asyncio
async def test_global_concurrency_limit_enforced() -> None:
    """With global_limit=1, two concurrent submits do not overlap."""
    defn_a = _make_definition("agent-x", max_concurrent_runs=2)
    defn_b = _make_definition("agent-y", max_concurrent_runs=2)

    active: dict[str, int] = {"count": 0, "max_seen": 0}
    barrier = asyncio.Event()

    class SlowRunner:
        async def run(
            self,
            definition: AgentDefinition,
            *,
            prompt: str | None = None,
        ) -> RunReport:
            active["count"] += 1
            active["max_seen"] = max(active["max_seen"], active["count"])
            await barrier.wait()  # hold until released
            active["count"] -= 1
            return _canned_report(definition.id)

    slow = SlowRunner()
    executor = RunExecutor(
        slow,  # type: ignore[arg-type]
        {"agent-x": defn_a, "agent-y": defn_b},
        global_limit=1,
    )

    req_x = RunRequest(agent_id="agent-x", reason="test")
    req_y = RunRequest(agent_id="agent-y", reason="test")

    # Launch both but let them contend on the global semaphore.
    task_x = asyncio.create_task(executor.submit(req_x))
    # Give task_x time to enter the semaphore and reach the barrier.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    task_y = asyncio.create_task(executor.submit(req_y))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # Release the barrier — both tasks can now complete sequentially.
    barrier.set()
    await asyncio.gather(task_x, task_y)

    # With global_limit=1 the two runs must have been serialised.
    assert active["max_seen"] == 1


@pytest.mark.asyncio
async def test_per_agent_concurrency_limit_enforced() -> None:
    """Per-agent max_concurrent_runs=1 prevents two simultaneous runs of the same agent."""
    defn = _make_definition("single-agent", max_concurrent_runs=1)

    active: dict[str, int] = {"count": 0, "max_seen": 0}
    barrier = asyncio.Event()

    class SlowRunner:
        async def run(
            self,
            definition: AgentDefinition,
            *,
            prompt: str | None = None,
        ) -> RunReport:
            active["count"] += 1
            active["max_seen"] = max(active["max_seen"], active["count"])
            await barrier.wait()
            active["count"] -= 1
            return _canned_report(definition.id)

    slow = SlowRunner()
    executor = RunExecutor(
        slow,  # type: ignore[arg-type]
        {"single-agent": defn},
        global_limit=4,
    )

    req = RunRequest(agent_id="single-agent", reason="test")
    task1 = asyncio.create_task(executor.submit(req))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task2 = asyncio.create_task(executor.submit(req))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    barrier.set()
    await asyncio.gather(task1, task2)

    assert active["max_seen"] == 1


@pytest.mark.asyncio
async def test_redis_advisory_lock_skips_when_locked() -> None:
    """When the Redis SET NX returns falsy, the run is skipped."""

    class FakeRedis:
        def __init__(self) -> None:
            self.set_calls: int = 0
            self.delete_calls: int = 0

        async def set(
            self,
            key: str,
            value: str,
            *,
            nx: bool = False,
            ex: int = 0,
        ) -> Any:
            self.set_calls += 1
            return None  # simulate lock already held

        async def delete(self, key: str) -> None:
            self.delete_calls += 1

    defn = _make_definition("locked-agent")
    stub = StubRunner()
    fake_redis = FakeRedis()
    executor = RunExecutor(
        stub,  # type: ignore[arg-type]
        {"locked-agent": defn},
        global_limit=2,
        redis=fake_redis,
    )

    await executor.submit(RunRequest(agent_id="locked-agent", reason="test"))

    assert stub.called == []
    assert fake_redis.set_calls == 1
    # delete should NOT be called because we returned before acquiring
    assert fake_redis.delete_calls == 0


@pytest.mark.asyncio
async def test_redis_advisory_lock_releases_after_run() -> None:
    """When the Redis lock is acquired, it is released (deleted) after run completion."""

    class FakeRedis:
        def __init__(self) -> None:
            self.set_calls: int = 0
            self.delete_calls: int = 0

        async def set(
            self,
            key: str,
            value: str,
            *,
            nx: bool = False,
            ex: int = 0,
        ) -> Any:
            self.set_calls += 1
            return True  # lock acquired

        async def delete(self, key: str) -> None:
            self.delete_calls += 1

    defn = _make_definition("unlocked-agent")
    stub = StubRunner()
    fake_redis = FakeRedis()
    executor = RunExecutor(
        stub,  # type: ignore[arg-type]
        {"unlocked-agent": defn},
        global_limit=2,
        redis=fake_redis,
    )

    await executor.submit(RunRequest(agent_id="unlocked-agent", reason="test"))

    assert stub.called == ["unlocked-agent"]
    assert fake_redis.set_calls == 1
    assert fake_redis.delete_calls == 1
