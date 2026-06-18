"""Tests for global config loading (load_global_config)."""

from pathlib import Path

import pytest

from saga_agents.config.loader import load_global_config


def test_load_global_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAGA_MCP_TOKEN", "secret")
    (tmp_path / "agents.yaml").write_text(
        "mcp:\n  base_url: http://mcp:8100/mcp\n  bearer_token: ${SAGA_MCP_TOKEN}\n"
        "ollama:\n  base_url: http://ollama:11434\n  default_model: qwen2.5:14b\n"
        "redis:\n  url: redis://redis:6379/0\n  event_channel: saga:events\n"
    )
    cfg = load_global_config(str(tmp_path / "agents.yaml"))
    assert cfg.mcp.bearer_token == "secret"
    assert cfg.runtime.max_concurrent_runs_global == 2


def test_load_global_config_missing_env_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SAGA_MCP_TOKEN", raising=False)
    (tmp_path / "agents.yaml").write_text(
        "mcp:\n  base_url: http://mcp:8100/mcp\n  bearer_token: ${SAGA_MCP_TOKEN}\n"
        "ollama:\n  base_url: http://ollama:11434\n  default_model: qwen2.5:14b\n"
        "redis:\n  url: redis://redis:6379/0\n  event_channel: saga:events\n"
    )
    from saga_agents.core.errors import ConfigError

    with pytest.raises(ConfigError):
        load_global_config(str(tmp_path / "agents.yaml"))


def test_load_global_config_file_not_found() -> None:
    from saga_agents.core.errors import ConfigError

    with pytest.raises(ConfigError, match="Cannot read"):
        load_global_config("/nonexistent/path/agents.yaml")


def test_load_global_config_agents_dir_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SAGA_MCP_TOKEN", "tok")
    yaml_text = (
        "mcp:\n  base_url: http://mcp:8100/mcp\n  bearer_token: ${SAGA_MCP_TOKEN}\n"
        "ollama:\n  base_url: http://ollama:11434\n  default_model: llama3\n"
        "redis:\n  url: redis://redis:6379/0\n  event_channel: saga:events\n"
    )
    (tmp_path / "agents.yaml").write_text(yaml_text)
    cfg = load_global_config(str(tmp_path / "agents.yaml"))
    assert cfg.agents_dir == "config/agents"
