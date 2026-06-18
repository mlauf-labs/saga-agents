"""Tests for SqliteProposalStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from saga_agents.proposals.store import SqliteProposalStore


@pytest.fixture
async def store(tmp_path: Path) -> SqliteProposalStore:
    """Return an initialised SqliteProposalStore backed by a temp DB."""
    s = SqliteProposalStore(str(tmp_path / "proposals.db"))
    await s.init()
    return s


async def test_add_list_and_set_status(store: SqliteProposalStore) -> None:
    """add -> list_pending -> set_status("applied") -> get shows applied, not in pending."""
    rec = await store.add("a1", "r1", "merge_events", {"x": 1}, "dupes")
    assert rec.status == "pending"

    pending = await store.list_pending()
    assert len(pending) == 1
    assert pending[0].action == "merge_events"

    await store.set_status(rec.id, "applied")
    fetched = await store.get(rec.id)
    assert fetched is not None
    assert fetched.status == "applied"

    assert await store.list_pending() == []


async def test_reject_path(store: SqliteProposalStore) -> None:
    """set_status("rejected") is persisted and record no longer appears in list_pending."""
    rec = await store.add("a2", "r2", "delete_event", {"event_id": "e1"}, "stale")

    pending_before = await store.list_pending()
    assert len(pending_before) == 1

    await store.set_status(rec.id, "rejected")

    fetched = await store.get(rec.id)
    assert fetched is not None
    assert fetched.status == "rejected"

    assert await store.list_pending() == []


async def test_arguments_round_trip(store: SqliteProposalStore) -> None:
    """arguments dict survives a JSON round-trip through SQLite."""
    args: dict[str, object] = {
        "nested": {"key": "value"},
        "items": [1, 2, 3],
        "flag": True,
    }
    rec = await store.add("a3", "r3", "some_action", args, "test")
    fetched = await store.get(rec.id)
    assert fetched is not None
    assert fetched.arguments == args


async def test_get_unknown_returns_none(store: SqliteProposalStore) -> None:
    """get() returns None for an unknown proposal ID."""
    result = await store.get("does-not-exist")
    assert result is None


async def test_list_pending_filter_by_agent_id(store: SqliteProposalStore) -> None:
    """list_pending filters by agent_id when provided."""
    await store.add("agent-x", "r1", "action_a", {}, "reason")
    await store.add("agent-y", "r2", "action_b", {}, "reason")

    x_pending = await store.list_pending("agent-x")
    assert len(x_pending) == 1
    assert x_pending[0].agent_id == "agent-x"

    all_pending = await store.list_pending()
    assert len(all_pending) == 2


async def test_set_status_with_error(store: SqliteProposalStore) -> None:
    """set_status stores the error message when provided."""
    rec = await store.add("a4", "r4", "risky_action", {}, "worth a try")
    await store.set_status(rec.id, "failed", error="connection timeout")

    fetched = await store.get(rec.id)
    assert fetched is not None
    assert fetched.status == "failed"
    assert fetched.error == "connection timeout"
