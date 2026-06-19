"""Tests for parse_agent_markdown and load_agent_files."""

from pathlib import Path

import pytest

from saga_agents.config.loader import load_agent_files, parse_agent_markdown
from saga_agents.core.errors import ConfigError

GOOD = """---
id: demo
autonomy: proposal
tools:
  allow: [get_timeline, merge_events]
  write: [merge_events]
triggers:
  - type: schedule
    cron: "0 3 * * *"
---
You are a demo agent.
"""


def test_parse_splits_config_and_prompt() -> None:
    d = parse_agent_markdown(GOOD, source="demo.md")
    assert d.id == "demo"
    assert d.autonomy == "proposal"
    assert d.tools.write == ["merge_events"]
    assert d.system_prompt == "You are a demo agent."
    assert d.triggers[0].cron == "0 3 * * *"  # type: ignore[union-attr]


def test_empty_body_raises() -> None:
    text = "---\nid: x\ntools:\n  allow: []\n---\n   \n"
    with pytest.raises(ConfigError):
        parse_agent_markdown(text, source="x.md")


def test_missing_frontmatter_raises() -> None:
    with pytest.raises(ConfigError):
        parse_agent_markdown("no frontmatter here", source="x.md")


def test_write_not_subset_of_allow_raises() -> None:
    text = "---\nid: x\ntools:\n  allow: [a]\n  write: [b]\n---\nbody\n"
    with pytest.raises(ConfigError):
        parse_agent_markdown(text, source="x.md")


def test_unclosed_frontmatter_raises() -> None:
    text = "---\nid: x\ntools:\n  allow: []\nbody without closing fence\n"
    with pytest.raises(ConfigError, match="unclosed"):
        parse_agent_markdown(text, source="x.md")


def test_env_resolution_in_frontmatter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_MODEL", "llama3:8b")
    text = "---\nid: env-agent\nmodel: ${MY_MODEL}\n---\nHello.\n"
    d = parse_agent_markdown(text, source="env-agent.md")
    assert d.model == "llama3:8b"


# ---------------------------------------------------------------------------
# load_agent_files tests
# ---------------------------------------------------------------------------


def _write_agent(tmp_path: Path, filename: str, agent_id: str, body: str = "Hello.") -> None:
    content = f"---\nid: {agent_id}\n---\n{body}\n"
    (tmp_path / filename).write_text(content, encoding="utf-8")


def test_load_agent_files_happy_path(tmp_path: Path) -> None:
    _write_agent(tmp_path, "a.md", "alpha")
    _write_agent(tmp_path, "b.md", "beta")
    agents = load_agent_files(str(tmp_path))
    assert len(agents) == 2
    ids = [a.id for a in agents]
    assert "alpha" in ids
    assert "beta" in ids


def test_load_agent_files_sorted_order(tmp_path: Path) -> None:
    _write_agent(tmp_path, "z.md", "zz")
    _write_agent(tmp_path, "a.md", "aa")
    agents = load_agent_files(str(tmp_path))
    assert agents[0].id == "aa"
    assert agents[1].id == "zz"


def test_load_agent_files_duplicate_id_raises(tmp_path: Path) -> None:
    _write_agent(tmp_path, "a.md", "dup")
    _write_agent(tmp_path, "b.md", "dup")
    with pytest.raises(ConfigError, match="Duplicate"):
        load_agent_files(str(tmp_path))


def test_load_agent_files_empty_dir(tmp_path: Path) -> None:
    agents = load_agent_files(str(tmp_path))
    assert agents == []


# ---------------------------------------------------------------------------
# Placeholder validation tests
# ---------------------------------------------------------------------------


def test_parse_rejects_unknown_saga_placeholder() -> None:
    text = "---\nid: x\ntools:\n  allow: []\n---\nBody with {{saga.bogus_key}}.\n"
    with pytest.raises(ConfigError):
        parse_agent_markdown(text, source="x.md")


def test_parse_accepts_known_saga_placeholder() -> None:
    text = "---\nid: x\ntools:\n  allow: []\n---\nArchive: {{saga.store_description}}.\n"
    d = parse_agent_markdown(text, source="x.md")
    assert "{{saga.store_description}}" in d.system_prompt
