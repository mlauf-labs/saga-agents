"""Tests for the Ollama model factory."""

from __future__ import annotations

from saga_agents.runtime.model import build_model


def test_build_model_targets_ollama_openai_endpoint() -> None:
    model = build_model("http://ollama:11434", "qwen2.5:14b")
    assert model is not None  # smoke: constructs without error
