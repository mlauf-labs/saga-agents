"""Tests for saga_agents.core.logging — verifies get_logger does not raise."""

from __future__ import annotations

import pytest

from saga_agents.core.logging import get_logger


def test_info_does_not_raise(capsys: pytest.CaptureFixture[str]) -> None:
    """get_logger(...).info() must not raise AttributeError or any other error."""
    log = get_logger("test.info")
    log.info("hello", key="value")  # must not raise


def test_warning_does_not_raise(capsys: pytest.CaptureFixture[str]) -> None:
    """get_logger(...).warning() must not raise."""
    log = get_logger("test.warning")
    log.warning("w", a=1)  # must not raise


def test_debug_does_not_raise() -> None:
    log = get_logger("test.debug")
    log.debug("dbg", x=42)


def test_error_does_not_raise() -> None:
    log = get_logger("test.error")
    log.error("oops", code=500)


def test_returns_bound_logger_with_name() -> None:
    """The bound logger should carry the 'logger' context key."""
    log = get_logger("my.module")
    # structlog bound loggers expose ._context on the wrapper
    ctx: dict[str, object] = log._context
    assert ctx.get("logger") == "my.module"
