"""Tests for saga_agents.core.env — environment-variable resolution."""

import pytest

from saga_agents.core.env import resolve_env
from saga_agents.core.errors import ConfigError


def test_default_used_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("X_NOPE", raising=False)
    assert resolve_env("${X_NOPE:-fallback}") == "fallback"


def test_missing_without_default_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("X_NOPE", raising=False)
    with pytest.raises(ConfigError):
        resolve_env("${X_NOPE}")


def test_existing_var_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_EXISTS", "hello")
    assert resolve_env("prefix_${X_EXISTS}_suffix") == "prefix_hello_suffix"


def test_existing_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_EXISTS", "real")
    assert resolve_env("${X_EXISTS:-fallback}") == "real"


def test_no_placeholders_passthrough() -> None:
    assert resolve_env("plain string") == "plain string"


def test_multiple_placeholders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A", "foo")
    monkeypatch.setenv("B", "bar")
    assert resolve_env("${A}-${B}") == "foo-bar"
