"""Config loaders: global YAML config and per-agent Markdown files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from saga_agents.config.models import AgentDefinition, GlobalConfig
from saga_agents.core.env import resolve_env, resolve_tree
from saga_agents.core.errors import ConfigError
from saga_agents.runtime.guidance import validate_placeholders


# ---------------------------------------------------------------------------
# Global config loader
# ---------------------------------------------------------------------------


def load_global_config(path: str = "config/agents.yaml") -> GlobalConfig:
    """Load and validate the global config from *path*.

    Reads the YAML file, resolves all ``${VAR}`` tokens, and validates the
    result against :class:`GlobalConfig`.

    Args:
        path: File-system path to the YAML config file.

    Returns:
        A validated :class:`GlobalConfig` instance.

    Raises:
        ConfigError: If the file cannot be read, env vars are missing, or the
            schema is invalid.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {path!r}: {exc}") from exc

    try:
        raw: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file {path!r} is not valid YAML: {exc}") from exc

    resolved = resolve_tree(raw)

    try:
        return GlobalConfig.model_validate(resolved)
    except ValidationError as exc:
        raise ConfigError(f"Config file {path!r} is schema-invalid: {exc}") from exc


# ---------------------------------------------------------------------------
# Agent Markdown loader
# ---------------------------------------------------------------------------


def resolve_env_in_yaml(text: str) -> str:
    """Resolve all ``${VAR}`` tokens in a raw YAML string before parsing.

    Args:
        text: Raw YAML frontmatter text (not yet parsed).

    Returns:
        The text with all env-var tokens substituted.

    Raises:
        ConfigError: If any variable is missing and has no default.
    """
    return resolve_env(text)


def parse_agent_markdown(text: str, *, source: str) -> AgentDefinition:
    """Parse an agent definition from a Markdown file with YAML frontmatter.

    The file must start with ``---\\n``, contain a closing ``\\n---\\n``, and
    have a non-empty body after the closing delimiter.  The body becomes the
    agent's ``system_prompt``.

    Args:
        text: Full text content of the Markdown file.
        source: Human-readable identifier used in error messages (e.g. filename).

    Returns:
        A validated :class:`AgentDefinition`.

    Raises:
        ConfigError: For missing/unclosed frontmatter, empty body, non-mapping
            frontmatter, or schema validation failure.
    """
    if not text.startswith("---\n"):
        raise ConfigError(f"Agent file {source!r} must start with a YAML frontmatter block (---).")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ConfigError(
            f"Agent file {source!r} has an unclosed frontmatter block (missing closing ---)."
        )
    front_raw = text[4:end]
    body = text[end + 5 :].strip()
    if not body:
        raise ConfigError(f"Agent file {source!r} has an empty system-prompt body.")
    data: Any = yaml.safe_load(resolve_env_in_yaml(front_raw)) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Agent file {source!r} frontmatter must be a YAML mapping.")
    validate_placeholders(body, source=source)
    data["system_prompt"] = body
    try:
        return AgentDefinition.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Agent file {source!r} is invalid: {exc}") from exc


def load_agent_files(agents_dir: str) -> list[AgentDefinition]:
    """Load all ``*.md`` agent definitions from *agents_dir*.

    Files are processed in sorted (alphabetical) order.  Duplicate ``id``
    values across files raise :class:`ConfigError`.

    Args:
        agents_dir: Directory path containing agent Markdown files.

    Returns:
        List of validated :class:`AgentDefinition` instances.

    Raises:
        ConfigError: If any file fails to parse or if duplicate agent IDs are
            found.
    """
    base = Path(agents_dir)
    agents: list[AgentDefinition] = []
    seen_ids: dict[str, str] = {}  # id → filename

    for md_path in sorted(base.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        agent = parse_agent_markdown(text, source=md_path.name)
        if agent.id in seen_ids:
            raise ConfigError(
                f"Duplicate agent id {agent.id!r} found in {md_path.name!r} "
                f"(already defined in {seen_ids[agent.id]!r})."
            )
        seen_ids[agent.id] = md_path.name
        agents.append(agent)

    return agents
