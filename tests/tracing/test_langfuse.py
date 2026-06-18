"""Tests for Langfuse tracing gate."""

from __future__ import annotations

import os

import pytest

from saga_agents.config.models import LangfuseSettings
from saga_agents.tracing.langfuse import configure_tracing


def test_tracing_disabled_without_keys() -> None:
    assert configure_tracing(LangfuseSettings(public_key="", secret_key="")) is False


def test_tracing_returns_false_and_no_env_leak_when_logfire_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """configure_tracing must return False (not raise) and must NOT set OTEL env vars
    when logfire.configure raises."""
    import saga_agents.tracing.langfuse as tracing_mod

    def _raise(**_kwargs: object) -> None:
        raise RuntimeError("logfire boom")

    monkeypatch.setattr(tracing_mod, "_configured", False)
    # String target avoids a typed attribute access on the imported `logfire`
    # module, which mypy strict treats as a non-exported attribute.
    monkeypatch.setattr("saga_agents.tracing.langfuse.logfire.configure", _raise)
    monkeypatch.setattr(tracing_mod._log, "warning", lambda *_a, **_kw: None)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)

    result = configure_tracing(
        LangfuseSettings(public_key="pk-test", secret_key="sk-test")
    )

    assert result is False
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in os.environ
    assert "OTEL_EXPORTER_OTLP_HEADERS" not in os.environ
