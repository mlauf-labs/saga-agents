"""Redis pub/sub listener with per-agent debounce."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

from saga_agents.config.models import AgentDefinition, EventTrigger
from saga_agents.triggers.base import RunRequest
from saga_agents.triggers.executor import RunExecutor

log = logging.getLogger(__name__)

# How often the tick loop checks debouncers (seconds).
_TICK_INTERVAL: float = 5.0


class Debouncer:
    """Single-agent debounce gate.

    Call :meth:`mark` whenever a relevant event arrives.  The quiet-window
    clock starts on the *first* mark after a reset; subsequent marks in the
    same burst do **not** restart the clock (the window keeps ticking from the
    first signal, collapsing a burst into one run).

    :meth:`due` returns ``True`` once *delay_seconds* have elapsed since that
    first mark and at least one mark has been received since the last
    :meth:`reset`.

    Args:
        delay_seconds: Quiet-window length in seconds.
        clock: Callable returning a monotonic timestamp.  Defaults to
            :func:`time.monotonic` (injectable for testing).
    """

    def __init__(
        self,
        delay_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._delay = delay_seconds
        self._clock = clock
        self._last_mark: float | None = None
        self._pending: bool = False

    def mark(self) -> None:
        """Record that a triggering event was observed.

        Only the first mark after a reset starts the quiet-window clock.
        Subsequent marks within the same pending window are ignored so that a
        burst of events is collapsed into a single run.
        """
        if not self._pending:
            self._last_mark = self._clock()
            self._pending = True

    def due(self) -> bool:
        """Return ``True`` iff the quiet window has elapsed since the first mark.

        Returns:
            ``True`` when a mark is pending and at least *delay_seconds* have
            passed since the first :meth:`mark` since the last reset.
        """
        if not self._pending or self._last_mark is None:
            return False
        return self._clock() - self._last_mark >= self._delay

    def reset(self) -> None:
        """Clear the pending flag.  A new :meth:`mark` re-arms the debouncer."""
        self._pending = False


# ---------------------------------------------------------------------------
# Per-agent trigger state
# ---------------------------------------------------------------------------


class _AgentTriggerState:
    """Associates an agent's EventTrigger with its Debouncer."""

    __slots__ = ("agent_id", "debouncer", "last_topic", "on")

    def __init__(
        self,
        agent_id: str,
        on: frozenset[str],
        debouncer: Debouncer,
    ) -> None:
        self.agent_id = agent_id
        self.on = on
        self.debouncer = debouncer
        self.last_topic: str = "debounced"


# ---------------------------------------------------------------------------
# RedisListener
# ---------------------------------------------------------------------------


class RedisListener:
    """Subscribes to a Redis pub/sub channel and dispatches debounced runs.

    For each :class:`~saga_agents.config.models.EventTrigger` found in the
    agent definitions, a :class:`Debouncer` is maintained.  Incoming JSON
    messages carry a ``topic`` field; when the topic matches a trigger's ``on``
    list the corresponding debouncer is :meth:`~Debouncer.mark`-ed.  A
    background tick loop checks :meth:`~Debouncer.due` every
    :data:`_TICK_INTERVAL` seconds and submits a :class:`RunRequest` for any
    debouncer that fires.

    Args:
        redis: An ``redis.asyncio`` client instance.
        channel: The pub/sub channel name to subscribe to.
        definitions: Mapping of agent_id → AgentDefinition.
        executor: The :class:`RunExecutor` to dispatch runs to.
    """

    def __init__(
        self,
        redis: Any,  # noqa: ANN401
        channel: str,
        definitions: dict[str, AgentDefinition],
        executor: RunExecutor,
    ) -> None:
        self._redis = redis
        self._channel = channel
        self._executor = executor
        self._states: list[_AgentTriggerState] = []

        for agent_id, defn in definitions.items():
            if not defn.enabled:
                continue
            for trigger in defn.triggers:
                if isinstance(trigger, EventTrigger):
                    delay = max(trigger.debounce_minutes * 60.0, 1.0)
                    state = _AgentTriggerState(
                        agent_id=agent_id,
                        on=frozenset(trigger.on),
                        debouncer=Debouncer(delay),
                    )
                    self._states.append(state)

        self._pubsub: Any | None = None  # noqa: ANN401
        self._listener_task: asyncio.Task[None] | None = None
        self._tick_task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        """Subscribe to Redis and start the listener + tick loops.

        Returns immediately after spawning background tasks.  Call
        :meth:`stop` to shut them down.
        """
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(self._channel)
        log.info("redis_listener_subscribed channel=%s", self._channel)

        self._listener_task = asyncio.create_task(self._listener_loop())
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        """Cancel background tasks and unsubscribe from Redis."""
        for task in (self._listener_task, self._tick_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe(self._channel)
                await self._pubsub.aclose()
            except Exception as exc:  # noqa: BLE001
                log.warning("redis_listener_unsubscribe_error error=%s", exc)
        log.info("redis_listener_stopped channel=%s", self._channel)

    # ------------------------------------------------------------------
    # Internal loops
    # ------------------------------------------------------------------

    async def _listener_loop(self) -> None:
        """Read messages from pub/sub and mark matching debouncers."""
        assert self._pubsub is not None
        async for raw in self._pubsub.listen():
            try:
                if raw.get("type") != "message":
                    continue
                data = raw.get("data", b"")
                if isinstance(data, bytes):
                    data = data.decode()
                msg: dict[str, Any] = json.loads(data)
                topic: str = msg.get("topic", "")
                self._handle_message(topic, msg)
            except Exception as exc:  # noqa: BLE001
                log.warning("redis_listener_message_error error=%s", exc)

    def _handle_message(self, topic: str, msg: dict[str, Any]) -> None:
        """Mark debouncers for all agents that listen to *topic*."""
        for state in self._states:
            if topic in state.on:
                state.last_topic = topic
                state.debouncer.mark()
                log.debug(
                    "debouncer_marked agent_id=%s topic=%s",
                    state.agent_id,
                    topic,
                )

    async def _tick_loop(self) -> None:
        """Periodically check debouncers and submit due runs."""
        while True:
            await asyncio.sleep(_TICK_INTERVAL)
            for state in self._states:
                if state.debouncer.due():
                    state.debouncer.reset()
                    req = RunRequest(
                        agent_id=state.agent_id,
                        reason=f"event:{state.last_topic}",
                    )
                    log.debug(
                        "debouncer_fired agent_id=%s reason=%s",
                        state.agent_id,
                        req.reason,
                    )
                    await self._executor.submit(req)
