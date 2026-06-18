"""Tests for the external trigger HTTP API (build_api)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from saga_agents.config.models import AgentDefinition, Limits, ToolsSpec
from saga_agents.triggers.api import build_api
from saga_agents.triggers.base import RunRequest


# ---------------------------------------------------------------------------
# Stubs and helpers
# ---------------------------------------------------------------------------


class _StubExecutor:
    """Records RunRequests submitted to it."""

    def __init__(self) -> None:
        self.submitted: list[RunRequest] = []

    async def submit(self, req: RunRequest) -> None:  # noqa: D102
        self.submitted.append(req)


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_healthz_ok() -> None:
    """/healthz returns 200 and {"status": "ok"}."""
    client = TestClient(build_api(_StubExecutor(), {}, expected_token="t"))  # type: ignore[arg-type]
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_trigger_requires_token() -> None:
    """POST /triggers/{agent_id} returns 403 without a valid token."""
    defs = {"a": _make_definition("a")}
    client = TestClient(build_api(_StubExecutor(), defs, expected_token="t"))  # type: ignore[arg-type]
    assert client.post("/triggers/a").status_code == 403


def test_trigger_with_valid_token_and_known_agent_returns_202() -> None:
    """POST /triggers/{agent_id} with valid token and known agent returns 202."""
    stub = _StubExecutor()
    defs = {"a": _make_definition("a")}
    client = TestClient(build_api(stub, defs, expected_token="t"))  # type: ignore[arg-type]
    response = client.post("/triggers/a", headers={"Authorization": "Bearer t"})
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert body["agent_id"] == "a"


def test_trigger_with_valid_token_calls_executor() -> None:
    """POST /triggers/{agent_id} with valid token submits a RunRequest to executor."""
    stub = _StubExecutor()
    defs = {"a": _make_definition("a")}
    client = TestClient(build_api(stub, defs, expected_token="t"))  # type: ignore[arg-type]
    client.post("/triggers/a", headers={"Authorization": "Bearer t"})
    assert len(stub.submitted) == 1
    assert stub.submitted[0].agent_id == "a"
    assert stub.submitted[0].reason == "external"


def test_trigger_unknown_agent_returns_404() -> None:
    """POST /triggers/{agent_id} with valid token but unknown agent returns 404."""
    defs = {"a": _make_definition("a")}
    client = TestClient(build_api(_StubExecutor(), defs, expected_token="t"))  # type: ignore[arg-type]
    response = client.post("/triggers/missing", headers={"Authorization": "Bearer t"})
    assert response.status_code == 404


def test_trigger_wrong_token_returns_403() -> None:
    """POST /triggers/{agent_id} with wrong token returns 403."""
    defs = {"a": _make_definition("a")}
    client = TestClient(build_api(_StubExecutor(), defs, expected_token="secret"))  # type: ignore[arg-type]
    response = client.post("/triggers/a", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 403


def test_build_api_accepts_proposal_store_none() -> None:
    """build_api is callable with proposal_store=None (default)."""
    app = build_api(_StubExecutor(), {}, expected_token="t", proposal_store=None)  # type: ignore[arg-type]
    assert app is not None


def test_build_api_accepts_proposal_store_object() -> None:
    """build_api is callable with an arbitrary proposal_store object."""

    class _FakeStore:
        pass

    app = build_api(_StubExecutor(), {}, expected_token="t", proposal_store=_FakeStore())  # type: ignore[arg-type]
    assert app is not None
