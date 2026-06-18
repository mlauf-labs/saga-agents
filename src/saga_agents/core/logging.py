"""Structured JSON logging via structlog.

Usage::

    from saga_agents.core.logging import get_logger

    log = get_logger(__name__)
    log.info("agent_started", agent_id="event-deduplicator")
"""

from __future__ import annotations

import sys
from typing import Any

import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    cache_logger_on_first_use=True,
)


def get_logger(name: str) -> Any:
    """Return a structlog bound logger configured for JSON output.

    The logger name is injected as a bound context value (key ``"logger"``)
    rather than via ``add_logger_name``, which requires a stdlib logger with a
    ``.name`` attribute.  ``PrintLogger`` has no such attribute, so
    ``add_logger_name`` raises ``AttributeError`` under pytest.  Binding the
    name explicitly avoids that entirely.

    Args:
        name: Logger name, e.g. ``"saga_agents.runtime.runner"``.

    Returns:
        A structlog bound logger with ``logger=name`` pre-bound.
    """
    return structlog.get_logger().bind(logger=name)
