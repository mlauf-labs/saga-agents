"""Tests for apply_proposal."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from saga_agents.proposals.apply import apply_proposal
from saga_agents.proposals.store import ProposalRecord


def _make_record(
    action: str = "merge_events",
    arguments: dict[str, Any] | None = None,
) -> ProposalRecord:
    return ProposalRecord(
        id="p1",
        agent_id="a1",
        run_id="r1",
        action=action,
        arguments=arguments or {"canonical_event_id": "c"},
        rationale="test rationale",
        status="pending",
        created_at=datetime.now(UTC),
    )


async def test_apply_invokes_mcp_call() -> None:
    """apply_proposal calls mcp_call with (action, arguments)."""
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_call(action: str, args: dict[str, Any]) -> None:
        calls.append((action, args))

    rec = _make_record()
    await apply_proposal(rec, fake_call)
    assert calls == [("merge_events", {"canonical_event_id": "c"})]


async def test_apply_returns_mcp_call_result() -> None:
    """apply_proposal returns whatever mcp_call returns."""

    async def fake_call(action: str, args: dict[str, Any]) -> dict[str, str]:
        return {"ok": "true"}

    rec = _make_record()
    result = await apply_proposal(rec, fake_call)
    assert result == {"ok": "true"}


async def test_apply_propagates_exception() -> None:
    """apply_proposal does not swallow exceptions from mcp_call."""

    async def bad_call(action: str, args: dict[str, Any]) -> None:
        raise RuntimeError("mcp unavailable")

    rec = _make_record()
    with pytest.raises(RuntimeError, match="mcp unavailable"):
        await apply_proposal(rec, bad_call)


async def test_apply_passes_correct_arguments() -> None:
    """apply_proposal forwards record.arguments unchanged."""
    received: list[dict[str, Any]] = []

    async def capture(action: str, args: dict[str, Any]) -> None:
        received.append(args)

    complex_args: dict[str, Any] = {"ids": [1, 2, 3], "nested": {"k": "v"}}
    rec = _make_record(action="bulk_merge", arguments=complex_args)
    await apply_proposal(rec, capture)
    assert received == [complex_args]
