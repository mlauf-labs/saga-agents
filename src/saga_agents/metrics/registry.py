"""Prometheus registry and metric definitions for saga-agents."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

AGENT_REGISTRY = CollectorRegistry()

AGENT_RUNS = Counter(
    "saga_agent_runs_total",
    "Agent runs by agent, trigger, and result.",
    labelnames=("agent_id", "trigger", "result"),
    registry=AGENT_REGISTRY,
)
AGENT_RUN_DURATION = Histogram(
    "saga_agent_run_duration_seconds",
    "Agent run duration by agent.",
    labelnames=("agent_id",),
    registry=AGENT_REGISTRY,
)
AGENT_INFLIGHT = Gauge(
    "saga_agent_inflight",
    "Currently executing agent runs.",
    registry=AGENT_REGISTRY,
)
AGENT_CONCURRENCY_LIMIT = Gauge(
    "saga_agent_concurrency_limit",
    "Configured global concurrency limit.",
    registry=AGENT_REGISTRY,
)
AGENT_PROPOSALS = Counter(
    "saga_agent_proposals_total",
    "Proposals by terminal state.",
    labelnames=("state",),
    registry=AGENT_REGISTRY,
)
AGENT_TOKENS = Counter(
    "saga_agent_tokens_total",
    "LLM tokens by agent, model, and kind.",
    labelnames=("agent_id", "model", "kind"),
    registry=AGENT_REGISTRY,
)
