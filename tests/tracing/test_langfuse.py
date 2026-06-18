"""Tests for Langfuse tracing gate."""

from __future__ import annotations

from saga_agents.config.models import LangfuseSettings
from saga_agents.tracing.langfuse import configure_tracing


def test_tracing_disabled_without_keys() -> None:
    assert configure_tracing(LangfuseSettings(public_key="", secret_key="")) is False
