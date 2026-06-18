"""Ollama model factory via OpenAI-compatible provider."""

from __future__ import annotations

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


def build_model(ollama_base_url: str, model_name: str) -> OpenAIChatModel:
    """Construct an OpenAIChatModel targeting an Ollama instance.

    Args:
        ollama_base_url: Base URL of the Ollama server, e.g. ``"http://ollama:11434"``.
        model_name: Name of the model to use, e.g. ``"qwen2.5:14b"``.

    Returns:
        An :class:`OpenAIChatModel` configured to talk to Ollama's OpenAI-compatible API.
    """
    base = ollama_base_url.rstrip("/")
    provider = OpenAIProvider(base_url=f"{base}/v1", api_key="ollama")
    return OpenAIChatModel(model_name, provider=provider)
