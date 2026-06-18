"""Tests for the saga-agents error hierarchy."""

from saga_agents.core.errors import AgentsError, ConfigError, RunError


def test_config_error_is_agents_error() -> None:
    assert issubclass(ConfigError, AgentsError)


def test_run_error_is_agents_error() -> None:
    assert issubclass(RunError, AgentsError)
