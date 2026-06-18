"""Environment-variable resolution for YAML config values.

Supports ``${VAR}`` and ``${VAR:-default}`` syntax.  A missing variable with no
default raises :class:`saga_agents.core.errors.ConfigError`.
"""

from __future__ import annotations

import os
import re
from typing import Any

from saga_agents.core.errors import ConfigError

# Matches ${VAR} and ${VAR:-default}
_ENV_PATTERN: re.Pattern[str] = re.compile(
    r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}"
)


def resolve_env(value: str) -> str:
    """Resolve all ``${VAR}`` / ``${VAR:-default}`` tokens in *value*.

    Args:
        value: A string potentially containing ``${VAR}`` references.

    Returns:
        The string with all tokens substituted.

    Raises:
        ConfigError: If a variable is referenced without a default and is not
            set in the environment.
    """

    def _replace(match: re.Match[str]) -> str:
        name: str = match.group("name")
        default: str | None = match.group("default")
        env_val = os.environ.get(name)
        if env_val is not None:
            return env_val
        if default is not None:
            return default
        raise ConfigError(
            f"Environment variable {name!r} is not set and has no default value."
        )

    return _ENV_PATTERN.sub(_replace, value)


def resolve_tree(node: Any) -> Any:
    """Recursively resolve ``${VAR}`` tokens in a parsed YAML structure.

    Handles dicts, lists, and strings; other types are returned unchanged.

    Args:
        node: A YAML-parsed value (dict, list, str, int, bool, None, …).

    Returns:
        The same structure with all string values resolved.

    Raises:
        ConfigError: If any variable reference cannot be resolved.
    """
    if isinstance(node, dict):
        return {k: resolve_tree(v) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_tree(item) for item in node]
    if isinstance(node, str):
        return resolve_env(node)
    return node
