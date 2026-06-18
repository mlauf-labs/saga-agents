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
            self.eval_calls: int = 0

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

        async def eval(self, script: str, numkeys: int, *args: Any) -> Any:
            self.eval_calls += 1
            return 0

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
    # eval/delete should NOT be called because we returned before acquiring
    assert fake_redis.eval_calls == 0


@pytest.mark.asyncio
async def test_redis_advisory_lock_releases_after_run() -> None:
    """When the Redis lock is acquired, it is released via compare-and-delete after run."""

    stored_token: dict[str, str] = {}

    class FakeRedis:
        def __init__(self) -> None:
            self.set_calls: int = 0
            self.eval_calls: int = 0
            self.eval_key: str | None = None
            self.eval_token: str | None = None

        async def set(
            self,
            key: str,
            value: str,
            *,
            nx: bool = False,
            ex: int = 0,
        ) -> Any:
            self.set_calls += 1
            stored_token[key] = value  # record the token that was set
            return True  # lock acquired

        async def eval(self, script: str, numkeys: int, *args: Any) -> Any:
            self.eval_calls += 1
            self.eval_key = args[0]
            self.eval_token = args[1]
            return 1

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
    # ownership-guarded release: eval called exactly once
    assert fake_redis.eval_calls == 1
    # the token passed to eval must match the token stored at acquire time
    lock_key = "agent:lock:unlocked-agent"
    assert fake_redis.eval_key == lock_key
    assert fake_redis.eval_token == stored_token[lock_key]


@pytest.mark.asyncio
async def test_redis_advisory_lock_does_not_delete_foreign_lock() -> None:
    """If the lock key is no longer owned (expired and re-acquired), eval does not delete it."""

    class FakeRedis:
        """Simulates a Redis where the lock key holds a different token (re-acquired by another run)."""

        def __init__(self) -> None:
            self.eval_calls: int = 0
            self.eval_token_passed: str | None = None
            self._store: dict[str, str] = {}

        async def set(
            self,
            key: str,
            value: str,
            *,
            nx: bool = False,
            ex: int = 0,
        ) -> Any:
            self._store[key] = value
            return True

        async def eval(self, script: str, numkeys: int, *args: Any) -> Any:
            self.eval_calls += 1
            self.eval_token_passed = args[1]
            key = args[0]
            token = args[1]
            # Simulate another process having replaced the lock value
            current = self._store.get(key)
            if current == token:
                del self._store[key]
                return 1
            return 0  # token mismatch — do not delete

    defn = _make_definition("ownership-agent")
    stub = StubRunner()
    fake_redis = FakeRedis()
    executor = RunExecutor(
        stub,  # type: ignore[arg-type]
        {"ownership-agent": defn},
        global_limit=2,
        redis=fake_redis,
    )

    # Corrupt the lock between acquire and release to simulate expiry+re-acquire
    original_run = stub.run

    async def run_and_corrupt(
        definition: AgentDefinition, *, prompt: str | None = None
    ) -> RunReport:
        # Replace the stored token with a foreign value mid-run
        key = f"agent:lock:{definition.id}"
        fake_redis._store[key] = "foreign-token"
        return await original_run(definition)

    stub.run = run_and_corrupt  # type: ignore[method-assign]

    await executor.submit(RunRequest(agent_id="ownership-agent", reason="test"))

    assert stub.called == ["ownership-agent"]
    # eval was called, but returned 0 (no delete) because token didn't match
    assert fake_redis.eval_calls == 1
    # the foreign token must NOT have been deleted
    assert fake_redis._store.get("agent:lock:ownership-agent") == "foreign-token"
