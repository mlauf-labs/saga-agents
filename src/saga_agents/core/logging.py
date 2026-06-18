"""Structured JSON logging via structlog.

Usage::

    from saga_agents.core.logging import get_logger

    log = get_logger(__name__)
    log.info("agent_started", agent_id="event-deduplicator")
"""

from __future__ import annotations

import logging
import sys

import structlog

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog bound logger configured for JSON output.

    Args:
        name: Logger name, e.g. ``"saga_agents.runtime.runner"``.

    Returns:
        A structlog bound logger instance.
    """
    _configure()
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
