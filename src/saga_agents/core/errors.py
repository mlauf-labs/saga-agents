"""Saga-agents error hierarchy.

All exceptions carry actionable messages — never raise a bare Exception.
"""


class AgentsError(Exception):
    """Base class for all saga-agents errors (actionable messages)."""


class ConfigError(AgentsError):
    """Invalid or missing configuration."""


class RunError(AgentsError):
    """A run could not be completed."""
