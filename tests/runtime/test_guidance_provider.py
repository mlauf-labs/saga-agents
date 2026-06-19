"""Tests for GuidanceProvider (TTL-cached MCP fetch)."""

from __future__ import annotations

import pytest

from saga_agents.core.errors import GuidanceFetchError
from saga_agents.runtime.guidance import GuidanceProvider

GUIDANCE = {
    "store_description": "Fam",
    "doctype_instructions": "",
    "metadata_instructions": "",
    "summary_instructions": "",
    "folder_instructions": "By member",
    "language": "English",
}


class _FakeServer:
    def __init__(self, result: object, calls: list[str]) -> None:
        self._result = result
        self._calls = calls

    async def __aenter__(self) -> _FakeServer:
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    async def direct_call_tool(self, name: str, args: object) -> object:
        self._calls.append(name)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _factory(result: object, calls: list[str]) -> object:
    def make(base_url: str, bearer_token: str) -> _FakeServer:
        return _FakeServer(result, calls)

    return make


@pytest.mark.asyncio
async def test_get_returns_guidance_and_caches_within_ttl() -> None:
    now = [0.0]
    calls: list[str] = []
    p = GuidanceProvider(
        _factory(GUIDANCE, calls),  # type: ignore[arg-type]
        "http://mcp/mcp",
        "tok",
        ttl_seconds=300.0,
        clock=lambda: now[0],
    )
    assert (await p.get())["folder_instructions"] == "By member"
    now[0] = 100.0
    await p.get()
    assert calls == ["get_store_guidance"]  # second call served from cache


@pytest.mark.asyncio
async def test_get_refetches_after_ttl() -> None:
    now = [0.0]
    calls: list[str] = []
    p = GuidanceProvider(
        _factory(GUIDANCE, calls),  # type: ignore[arg-type]
        "http://mcp/mcp",
        "tok",
        ttl_seconds=300.0,
        clock=lambda: now[0],
    )
    await p.get()
    now[0] = 301.0
    await p.get()
    assert calls == ["get_store_guidance", "get_store_guidance"]


@pytest.mark.asyncio
async def test_get_raises_guidance_fetch_error_on_failure() -> None:
    p = GuidanceProvider(
        _factory(RuntimeError("mcp down"), []),  # type: ignore[arg-type]
        "http://mcp/mcp",
        "tok",
    )
    with pytest.raises(GuidanceFetchError):
        await p.get()
