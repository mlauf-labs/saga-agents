"""Routing tests for RedisListener: message → debouncer → executor dispatch."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from saga_agents.config.models import AgentDefinition, EventTrigger
from saga_agents.triggers.base import RunRequest
from saga_agents.triggers.redis_listener import RedisListener

# ---------------------------------------------------------------------------
# Stub executor
# ---------------------------------------------------------------------------


class StubExecutor:
    """Records every RunRequest passed to submit()."""

    def __init__(self) -> None:
        self.calls: list[RunRequest] = []

    async def submit(self, req: RunRequest) -> None:
        self.calls.append(req)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_listener(
    debounce_minutes: int = 0,
    on: list[str] | None = None,
) -> tuple[RedisListener, StubExecutor]:
    """Build a RedisListener wired to a StubExecutor.

    Uses a 0-minute debounce so Debouncer.due() returns True immediately after
    the first mark (delay is clamped to 1.0 s by the listener, but the
    injected clock starts at 999 s, so the window is already elapsed).
    """
    on = on or ["document.ingested"]
    agent_id = "test-agent"
    defn = AgentDefinition(
        id=agent_id,
        enabled=True,
        triggers=[EventTrigger(type="event", topics=on, debounce_minutes=debounce_minutes)],
    )
    executor = StubExecutor()
    # redis is only used in run()/stop(); pass a minimal stub so __init__ works.
    listener = RedisListener(
        redis=AsyncMock(),
        channel="saga:events",
        definitions={agent_id: defn},
        executor=executor,  # type: ignore[arg-type]
    )
    # Override the debouncer clock: t=0 at mark time, t=2 at due() checks.
    # The listener clamps debounce to min 1.0 s, so t=2 satisfies due().
    now: list[float] = [0.0]
    for state in listener._states:
        state.debouncer._clock = lambda: now[0]
    # Expose so tests can advance the clock after calling _handle_message.
    listener._test_clock = now  # type: ignore[attr-defined]
    return listener, executor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_handle_message_marks_matching_debouncer() -> None:
    """_handle_message marks the debouncer for an agent whose topic matches."""
    listener, _ = _make_listener(on=["document.ingested"])
    assert len(listener._states) == 1
    state = listener._states[0]

    pending_before = state.debouncer._pending
    assert pending_before is False
    listener._handle_message("document.ingested", {"topic": "document.ingested"})
    pending_after = state.debouncer._pending
    assert pending_after is True
    assert state.last_topic == "document.ingested"


def test_handle_message_does_not_mark_unrelated_topic() -> None:
    """_handle_message leaves the debouncer untouched for topics not in 'on'."""
    listener, _ = _make_listener(on=["document.ingested"])
    state = listener._states[0]

    listener._handle_message("document.deleted", {"topic": "document.deleted"})
    assert state.debouncer._pending is False


@pytest.mark.asyncio
async def test_dispatch_after_debounce_window() -> None:
    """After marking + due window elapsed, _check_due_and_dispatch submits once."""
    listener, executor = _make_listener(on=["document.ingested"])

    # Simulate an incoming event at t=0.
    listener._handle_message("document.ingested", {"topic": "document.ingested"})
    # Advance clock past the 1-second clamped minimum debounce.
    listener._test_clock[0] = 2.0  # type: ignore[attr-defined]

    # Drive one tick iteration directly (no sleep).
    await listener._check_due_and_dispatch()

    assert len(executor.calls) == 1
    req = executor.calls[0]
    assert req.agent_id == "test-agent"
    assert req.reason == "event:document.ingested"


@pytest.mark.asyncio
async def test_no_dispatch_without_mark() -> None:
    """_check_due_and_dispatch does nothing when no event has been received."""
    listener, executor = _make_listener(on=["document.ingested"])

    await listener._check_due_and_dispatch()

    assert executor.calls == []


@pytest.mark.asyncio
async def test_dispatch_not_re_triggered_after_reset() -> None:
    """A second tick after dispatch does not double-submit."""
    listener, executor = _make_listener(on=["document.ingested"])

    listener._handle_message("document.ingested", {"topic": "document.ingested"})
    listener._test_clock[0] = 2.0  # type: ignore[attr-defined]
    await listener._check_due_and_dispatch()  # first tick — submits
    await listener._check_due_and_dispatch()  # second tick — debouncer reset, no submit

    assert len(executor.calls) == 1


@pytest.mark.asyncio
async def test_submit_error_does_not_stop_loop() -> None:
    """A submit exception is caught; further dispatches still proceed."""
    listener, executor = _make_listener(on=["document.ingested"])

    call_count = 0

    async def failing_submit(req: RunRequest) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("boom")

    executor.submit = failing_submit  # type: ignore[method-assign]

    # First event — submit raises.
    listener._handle_message("document.ingested", {"topic": "document.ingested"})
    listener._test_clock[0] = 2.0  # type: ignore[attr-defined]
    await listener._check_due_and_dispatch()
    assert call_count == 1

    # Re-arm and second event — loop must still dispatch.
    listener._test_clock[0] = 3.0  # type: ignore[attr-defined]
    listener._handle_message("document.ingested", {"topic": "document.ingested"})
    listener._test_clock[0] = 6.0  # type: ignore[attr-defined]
    await listener._check_due_and_dispatch()
    assert call_count == 2
