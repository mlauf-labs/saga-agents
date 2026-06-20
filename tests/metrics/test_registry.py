from __future__ import annotations

from prometheus_client import generate_latest

from saga_agents.metrics.registry import AGENT_REGISTRY, AGENT_RUNS


def test_agent_runs_metric_emits() -> None:
    AGENT_RUNS.labels(agent_id="a", trigger="schedule", result="ok").inc()
    assert "saga_agent_runs_total" in generate_latest(AGENT_REGISTRY).decode()
