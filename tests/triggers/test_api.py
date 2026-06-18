"""Tests for the external trigger HTTP API (build_api)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient
from pydantic import BaseModel

from saga_agents.config.models import AgentDefinition, Limits, ToolsSpec
from saga_agents.proposals.store import ProposalRecord, SqliteProposalStore
from saga_agents.triggers.api import build_api
from saga_agents.triggers.base import RunRequest
from saga_agents.triggers.executor import RunExecutor


# ---------------------------------------------------------------------------
# Stubs and helpers
# ---------------------------------------------------------------------------


class _StubExecutor:
    """Records RunRequests submitted to it."""

    def __init__(self) -> None:
        self.submitted: list[RunRequest] = []

    async def submit(self, req: RunRequest) -> None:  # noqa: D102
        self.submitted.append(req)


def _stub() -> RunExecutor:
    """Return a _StubExecutor cast to RunExecutor for type-safe test builds."""
    return cast(RunExecutor, _StubExecutor())


def _make_definition(agent_id: str) -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        enabled=True,
        description="test agent",
        model=None,
        autonomy="autonomous",
        tools=ToolsSpec(),
        limits=Limits(),
        system_prompt="",
    )


async def _make_store(tmp_path: Path) -> SqliteProposalStore:
    store = SqliteProposalStore(str(tmp_path / "proposals.db"))
    await store.init()
    return store


async def _seed_proposal(store: SqliteProposalStore, agent_id: str = "agent-a") -> str:
    """Add one pending proposal and return its ID."""
    record: ProposalRecord = await store.add(
        agent_id, "run-1", "merge_events", {"x": 1}, "test rationale"
    )
    return record.id


# ---------------------------------------------------------------------------
# Existing trigger tests
# ---------------------------------------------------------------------------


def test_healthz_ok() -> None:
    """/healthz returns 200 and {"status": "ok"}."""
    client = TestClient(build_api(_stub(), {}, expected_token="t"))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_trigger_requires_token() -> None:
    """POST /triggers/{agent_id} returns 403 without a valid token."""
    defs = {"a": _make_definition("a")}
    client = TestClient(build_api(_stub(), defs, expected_token="t"))
    assert client.post("/triggers/a").status_code == 403


def test_trigger_with_valid_token_and_known_agent_returns_202() -> None:
    """POST /triggers/{agent_id} with valid token and known agent returns 202."""
    stub = _StubExecutor()
    defs = {"a": _make_definition("a")}
    client = TestClient(build_api(cast(RunExecutor, stub), defs, expected_token="t"))
    response = client.post("/triggers/a", headers={"Authorization": "Bearer t"})
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert body["agent_id"] == "a"


def test_trigger_with_valid_token_calls_executor() -> None:
    """POST /triggers/{agent_id} with valid token submits a RunRequest to executor."""
    stub = _StubExecutor()
    defs = {"a": _make_definition("a")}
    client = TestClient(build_api(cast(RunExecutor, stub), defs, expected_token="t"))
    client.post("/triggers/a", headers={"Authorization": "Bearer t"})
    assert len(stub.submitted) == 1
    assert stub.submitted[0].agent_id == "a"
    assert stub.submitted[0].reason == "external"


def test_trigger_unknown_agent_returns_404() -> None:
    """POST /triggers/{agent_id} with valid token but unknown agent returns 404."""
    defs = {"a": _make_definition("a")}
    client = TestClient(build_api(_stub(), defs, expected_token="t"))
    response = client.post("/triggers/missing", headers={"Authorization": "Bearer t"})
    assert response.status_code == 404


def test_trigger_wrong_token_returns_403() -> None:
    """POST /triggers/{agent_id} with wrong token returns 403."""
    defs = {"a": _make_definition("a")}
    client = TestClient(build_api(_stub(), defs, expected_token="secret"))
    response = client.post("/triggers/a", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 403


def test_build_api_accepts_proposal_store_none() -> None:
    """build_api is callable with proposal_store=None (default)."""
    app = build_api(_stub(), {}, expected_token="t", proposal_store=None)
    assert app is not None


async def test_build_api_accepts_proposal_store_object(tmp_path: Path) -> None:
    """build_api is callable with a real SqliteProposalStore instance."""
    store = SqliteProposalStore(str(tmp_path / "p.db"))
    await store.init()
    app = build_api(_stub(), {}, expected_token="t", proposal_store=store)
    from fastapi import FastAPI

    assert isinstance(app, FastAPI)
    client = TestClient(app)
    assert client.get("/healthz").status_code == 200


# ---------------------------------------------------------------------------
# Proposal endpoint tests
# ---------------------------------------------------------------------------


def test_list_proposals_no_store_returns_503() -> None:
    """GET /agents/{id}/proposals returns 503 when no proposal_store is configured."""
    client = TestClient(build_api(_stub(), {}, expected_token="t", proposal_store=None))
    response = client.get("/agents/agent-a/proposals", headers={"Authorization": "Bearer t"})
    assert response.status_code == 503


def test_list_proposals_requires_token() -> None:
    """GET /agents/{id}/proposals returns 403 without a token."""
    client = TestClient(build_api(_stub(), {}, expected_token="t", proposal_store=None))
    response = client.get("/agents/agent-a/proposals")
    assert response.status_code == 403


async def test_list_proposals_returns_pending(tmp_path: Path) -> None:
    """GET /agents/{id}/proposals lists pending proposals for that agent."""
    store = await _make_store(tmp_path)
    proposal_id = await _seed_proposal(store, "agent-a")

    client = TestClient(build_api(_stub(), {}, expected_token="t", proposal_store=store))
    response = client.get("/agents/agent-a/proposals", headers={"Authorization": "Bearer t"})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["id"] == proposal_id
    assert body[0]["status"] == "pending"


async def test_list_proposals_other_agent_empty(tmp_path: Path) -> None:
    """GET /agents/{id}/proposals returns empty list for an agent with no proposals."""
    store = await _make_store(tmp_path)
    await _seed_proposal(store, "agent-a")

    client = TestClient(build_api(_stub(), {}, expected_token="t", proposal_store=store))
    response = client.get("/agents/agent-b/proposals", headers={"Authorization": "Bearer t"})
    assert response.status_code == 200
    assert response.json() == []


async def test_approve_no_mcp_call_returns_503(tmp_path: Path) -> None:
    """POST /proposals/{id}/approve returns 503 when mcp_call is not configured."""
    store = await _make_store(tmp_path)
    proposal_id = await _seed_proposal(store)

    client = TestClient(build_api(_stub(), {}, expected_token="t", proposal_store=store))
    response = client.post(
        f"/proposals/{proposal_id}/approve", headers={"Authorization": "Bearer t"}
    )
    assert response.status_code == 503


async def test_approve_applies_proposal_and_sets_status(tmp_path: Path) -> None:
    """POST /proposals/{id}/approve invokes mcp_call and stores status 'applied'."""
    store = await _make_store(tmp_path)
    proposal_id = await _seed_proposal(store)

    mcp_calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_mcp(action: str, args: dict[str, Any]) -> dict[str, str]:
        mcp_calls.append((action, args))
        return {"merged": "ok"}

    client = TestClient(
        build_api(_stub(), {}, expected_token="t", proposal_store=store, mcp_call=fake_mcp)
    )
    response = client.post(
        f"/proposals/{proposal_id}/approve", headers={"Authorization": "Bearer t"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "applied"

    # mcp_call was invoked exactly once with the right action
    assert len(mcp_calls) == 1
    assert mcp_calls[0][0] == "merge_events"
    assert mcp_calls[0][1] == {"x": 1}

    # status persisted
    stored = await store.get(proposal_id)
    assert stored is not None
    assert stored.status == "applied"


async def test_approve_missing_proposal_returns_404(tmp_path: Path) -> None:
    """POST /proposals/{id}/approve returns 404 for an unknown proposal."""
    store = await _make_store(tmp_path)

    async def fake_mcp(action: str, args: dict[str, Any]) -> None:
        pass

    client = TestClient(
        build_api(_stub(), {}, expected_token="t", proposal_store=store, mcp_call=fake_mcp)
    )
    response = client.post("/proposals/nonexistent/approve", headers={"Authorization": "Bearer t"})
    assert response.status_code == 404


async def test_approve_mcp_failure_sets_failed_status(tmp_path: Path) -> None:
    """POST approve stores 'failed' status when mcp_call raises."""
    store = await _make_store(tmp_path)
    proposal_id = await _seed_proposal(store)

    async def failing_mcp(action: str, args: dict[str, Any]) -> None:
        raise RuntimeError("service down")

    client = TestClient(
        build_api(_stub(), {}, expected_token="t", proposal_store=store, mcp_call=failing_mcp)
    )
    response = client.post(
        f"/proposals/{proposal_id}/approve", headers={"Authorization": "Bearer t"}
    )
    assert response.status_code == 500
    assert "service down" in response.json()["error"]

    stored = await store.get(proposal_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error == "service down"


async def test_reject_proposal(tmp_path: Path) -> None:
    """POST /proposals/{id}/reject sets status 'rejected'."""
    store = await _make_store(tmp_path)
    proposal_id = await _seed_proposal(store)

    client = TestClient(build_api(_stub(), {}, expected_token="t", proposal_store=store))
    response = client.post(
        f"/proposals/{proposal_id}/reject", headers={"Authorization": "Bearer t"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "rejected"}

    stored = await store.get(proposal_id)
    assert stored is not None
    assert stored.status == "rejected"


async def test_reject_missing_proposal_returns_404(tmp_path: Path) -> None:
    """POST /proposals/{id}/reject returns 404 for unknown proposal."""
    store = await _make_store(tmp_path)

    client = TestClient(build_api(_stub(), {}, expected_token="t", proposal_store=store))
    response = client.post("/proposals/nonexistent/reject", headers={"Authorization": "Bearer t"})
    assert response.status_code == 404


async def test_reject_non_pending_proposal_returns_404(tmp_path: Path) -> None:
    """POST /proposals/{id}/reject returns 404 when proposal is not pending (e.g. applied)."""
    store = await _make_store(tmp_path)
    proposal_id = await _seed_proposal(store)
    # Move the proposal to 'applied' so it is no longer pending
    await store.set_status(proposal_id, "applied")

    client = TestClient(build_api(_stub(), {}, expected_token="t", proposal_store=store))
    response = client.post(
        f"/proposals/{proposal_id}/reject", headers={"Authorization": "Bearer t"}
    )
    assert response.status_code == 404

    # Status must remain 'applied' — reject must not overwrite it
    stored = await store.get(proposal_id)
    assert stored is not None
    assert stored.status == "applied"


async def test_approve_requires_token(tmp_path: Path) -> None:
    """POST /proposals/{id}/approve returns 403 without a token."""
    store = await _make_store(tmp_path)
    proposal_id = await _seed_proposal(store)

    async def fake_mcp(action: str, args: dict[str, Any]) -> None:
        pass

    client = TestClient(
        build_api(_stub(), {}, expected_token="t", proposal_store=store, mcp_call=fake_mcp)
    )
    response = client.post(f"/proposals/{proposal_id}/approve")
    assert response.status_code == 403


async def test_reject_requires_token(tmp_path: Path) -> None:
    """POST /proposals/{id}/reject returns 403 without a token."""
    store = await _make_store(tmp_path)
    proposal_id = await _seed_proposal(store)

    client = TestClient(build_api(_stub(), {}, expected_token="t", proposal_store=store))
    response = client.post(f"/proposals/{proposal_id}/reject")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Fix 2: non-JSON-serializable MCP result must not flip status to failed
# ---------------------------------------------------------------------------


class _PydanticResult(BaseModel):
    """A structured (non-dict) Pydantic model returned by a fake MCP call."""

    merged: str
    count: int


async def test_approve_non_json_native_result_returns_200_and_applied(
    tmp_path: Path,
) -> None:
    """POST approve with a Pydantic-model MCP result must return 200 and store 'applied'.

    Guards against the regression where JSONResponse serialization of a non-dict
    result would raise AFTER set_status("applied"), and the except branch would
    then wrongly overwrite the status with 'failed'.
    """
    store = await _make_store(tmp_path)
    proposal_id = await _seed_proposal(store)

    async def pydantic_mcp(action: str, args: dict[str, Any]) -> _PydanticResult:
        return _PydanticResult(merged="yes", count=3)

    client = TestClient(
        build_api(_stub(), {}, expected_token="t", proposal_store=store, mcp_call=pydantic_mcp)
    )
    response = client.post(
        f"/proposals/{proposal_id}/approve", headers={"Authorization": "Bearer t"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "applied"
    # The result must have been coerced to a JSON-safe form
    assert body["result"] is not None

    # Critically: stored status must be 'applied', NOT 'failed'
    stored = await store.get(proposal_id)
    assert stored is not None
    assert stored.status == "applied"
