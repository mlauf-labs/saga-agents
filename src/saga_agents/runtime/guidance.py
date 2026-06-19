"""Resolve {{saga.*}} prompt placeholders from saga-core's store guidance."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from typing import Any

from saga_agents.core.errors import ConfigError, GuidanceFetchError
from saga_agents.core.logging import get_logger

GUIDANCE_KEYS: frozenset[str] = frozenset(
    {
        "store_description",
        "doctype_instructions",
        "metadata_instructions",
        "summary_instructions",
        "folder_instructions",
        "language",
    }
)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*saga\.([a-z_]+)\s*\}\}")

_log = get_logger("saga_agents.runtime.guidance")


def referenced_keys(text: str) -> set[str]:
    """Return the set of saga placeholder keys referenced in *text*.

    Args:
        text: Prompt text potentially containing ``{{saga.<key>}}`` tokens.

    Returns:
        Set of key names found (without the ``saga.`` prefix).
    """
    return set(_PLACEHOLDER_RE.findall(text))


def validate_placeholders(text: str, *, source: str) -> None:
    """Raise :class:`ConfigError` if *text* references any unknown saga key.

    Args:
        text: Prompt text to validate.
        source: Human-readable source label (e.g. file path) for the error message.

    Raises:
        ConfigError: If any ``{{saga.<key>}}`` token uses an unrecognised key.
    """
    unknown = sorted(referenced_keys(text) - GUIDANCE_KEYS)
    if unknown:
        raise ConfigError(
            f"Agent file {source!r} references unknown saga placeholder(s) {unknown}. "
            f"Valid keys: {sorted(GUIDANCE_KEYS)}."
        )


def substitute(text: str, guidance: Mapping[str, str]) -> str:
    """Replace ``{{saga.<key>}}`` tokens in *text* with values from *guidance*.

    Unknown keys (not in *guidance*) are replaced with an empty string.
    Non-saga placeholders (e.g. ``{{other}}``) are left untouched.

    Args:
        text: Prompt text containing zero or more ``{{saga.<key>}}`` tokens.
        guidance: Mapping of guidance key → value.

    Returns:
        Text with all saga placeholders substituted.
    """
    return _PLACEHOLDER_RE.sub(lambda m: guidance.get(m.group(1), ""), text)


def _coerce_guidance(raw: Any) -> dict[str, str]:  # noqa: ANN401
    """Coerce the raw ``direct_call_tool`` result to ``dict[str, str]``.

    ``MCPServerStreamableHTTP.direct_call_tool`` returns a ``ToolResult``:
    ``str | BinaryContent | dict[str, Any] | list[Any] | Sequence[...]``.

    For ``get_store_guidance`` the server returns a structured dict, so
    ``direct_call_tool`` delivers it as ``dict[str, Any]`` (the MCP SDK
    unwraps any single-key ``{"result": …}`` wrapper before returning).
    A plain ``dict`` is therefore the expected shape here.

    Args:
        raw: The value returned by ``direct_call_tool``.

    Returns:
        A ``dict[str, str]`` of guidance key → value.

    Raises:
        GuidanceFetchError: If *raw* is not a dict or contains non-string values
            that cannot be coerced.
    """
    # Handle a {"result": <actual_dict>} wrapper that some MCP server
    # implementations emit (the pydantic-ai SDK normally unwraps this, but
    # custom or older server versions may not).
    data: Any = raw
    if isinstance(data, dict) and list(data.keys()) == ["result"]:
        data = data["result"]

    if not isinstance(data, dict):
        raise GuidanceFetchError(
            f"get_store_guidance returned unexpected type {type(data).__name__!r}; expected a dict."
        )

    out: dict[str, str] = {}
    for k, v in data.items():
        out[str(k)] = "" if v is None else str(v)
    return out


class GuidanceProvider:
    """TTL-cached provider of saga-core store guidance.

    Fetches guidance from the ``get_store_guidance`` MCP tool on first access
    and caches the result for *ttl_seconds*.  Subsequent calls within the TTL
    window return the cached value without opening a new MCP connection.

    Args:
        mcp_server_factory: Callable ``(base_url, bearer_token) -> server`` where
            *server* is an async context manager exposing ``direct_call_tool``.
        base_url: Full URL of the MCP server endpoint.
        bearer_token: API token sent as ``Authorization: Bearer …``.
        ttl_seconds: How long (in monotonic seconds) to cache the result.
        clock: Callable returning the current monotonic time; injectable for tests.
    """

    def __init__(
        self,
        mcp_server_factory: Callable[[str, str], Any],
        base_url: str,
        bearer_token: str,
        *,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._factory = mcp_server_factory
        self._base_url = base_url
        self._token = bearer_token
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[str, str] | None = None
        self._fetched_at: float | None = None

    async def get(self) -> dict[str, str]:
        """Return the current store guidance, fetching from MCP if the cache is stale.

        Returns:
            A ``dict[str, str]`` mapping guidance keys to their values.

        Raises:
            GuidanceFetchError: If the MCP call fails or returns an unexpected shape.
        """
        now = self._clock()
        if (
            self._cache is not None
            and self._fetched_at is not None
            and (now - self._fetched_at) < self._ttl
        ):
            return self._cache

        try:
            server = self._factory(self._base_url, self._token)
            async with server:
                raw = await server.direct_call_tool("get_store_guidance", {})
            guidance = _coerce_guidance(raw)
        except GuidanceFetchError:
            raise
        except Exception as exc:
            raise GuidanceFetchError(f"Could not fetch get_store_guidance from MCP: {exc}") from exc

        self._cache = guidance
        self._fetched_at = self._clock()
        _log.info("guidance_fetched", keys=list(guidance.keys()))
        return guidance
