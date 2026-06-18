"""Tests for build_service wiring (Task 17).

No servers, no uvicorn, no Redis connections are started — only the pure
assembly logic is exercised.
"""

from __future__ import annotations

from saga_agents.app import Service, build_service
from saga_agents.config.loader import load_agent_files, load_global_config
from saga_agents.config.models import GlobalConfig


def _config() -> GlobalConfig:
    """Return the real global config from config/agents.yaml."""
    return load_global_config("config/agents.yaml")


def test_build_service_returns_service() -> None:
    """build_service returns a Service instance."""
    config = _config()
    definitions = load_agent_files(config.agents_dir)
    service = build_service(config, definitions)
    assert isinstance(service, Service)


def test_executor_knows_both_agents() -> None:
    """The executor's internal definitions contain both enabled agents."""
    config = _config()
    definitions = load_agent_files(config.agents_dir)
    service = build_service(config, definitions)

    # Access the private dict — acceptable in unit tests for wiring verification.
    # Both reference agents are enabled=True.
    known_ids = set(service.executor._definitions.keys())
    assert "event-deduplicator" in known_ids
    assert "re-categorizer" in known_ids


def test_scheduler_jobs_count_matches_schedule_triggers() -> None:
    """Scheduler has one job per ScheduleTrigger across all enabled definitions.

    event-deduplicator: 1 schedule trigger (cron: "0 3 * * *")
    re-categorizer:     1 schedule trigger (cron: "0 4 * * *")
    Expected total: 2 jobs.
    """
    from saga_agents.config.models import ScheduleTrigger

    config = _config()
    definitions = load_agent_files(config.agents_dir)

    # Count expected schedule triggers from definitions.
    expected_job_count = sum(
        1 for d in definitions if d.enabled for t in d.triggers if isinstance(t, ScheduleTrigger)
    )

    service = build_service(config, definitions)
    actual_job_count = len(service.scheduler._scheduler.get_jobs())

    assert actual_job_count == expected_job_count
    assert expected_job_count == 2  # sanity check for the reference agents


def test_listener_is_none_without_redis() -> None:
    """When redis=None is passed, no RedisListener is created."""
    config = _config()
    definitions = load_agent_files(config.agents_dir)
    service = build_service(config, definitions, redis=None)
    assert service.listener is None


def test_api_is_fastapi_app() -> None:
    """The assembled api is a FastAPI application."""
    from fastapi import FastAPI

    config = _config()
    definitions = load_agent_files(config.agents_dir)
    service = build_service(config, definitions)
    assert isinstance(service.api, FastAPI)


def test_build_service_with_disabled_agent() -> None:
    """A disabled agent definition is excluded from the executor."""
    config = _config()
    definitions = load_agent_files(config.agents_dir)

    # Disable all agents to test the filter.
    disabled = [d.model_copy(update={"enabled": False}) for d in definitions]
    service = build_service(config, disabled)
    assert len(service.executor._definitions) == 0
