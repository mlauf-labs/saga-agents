"""External HTTP API for saga-agents: health check and trigger endpoints."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from saga_agents.config.models import AgentDefinition
from saga_agents.proposals.apply import apply_proposal
from saga_agents.proposals.store import SqliteProposalStore
from saga_agents.triggers.base import RunRequest
from saga_agents.triggers.executor import RunExecutor


def build_api(
    executor: RunExecutor,
    definitions: dict[str, AgentDefinition],
    *,
    expected_token: str,
    proposal_store: SqliteProposalStore | None = None,
    mcp_call: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
) -> FastAPI:
    """Construct and return a FastAPI application for the external trigger API.

    Endpoints:
    - ``GET /healthz`` — liveness probe.
    - ``POST /triggers/{agent_id}`` — trigger an agent run externally; requires
      ``Authorization: Bearer <expected_token>`` header.
    - ``GET /agents/{agent_id}/proposals`` — list pending proposals for an agent.
    - ``POST /proposals/{proposal_id}/approve`` — approve and apply a pending proposal.
    - ``POST /proposals/{proposal_id}/reject`` — reject a pending proposal.

    All non-health endpoints require ``Authorization: Bearer <expected_token>``.

    Args:
        executor: The :class:`RunExecutor` that dispatches agent runs.
        definitions: Mapping of agent ID to :class:`AgentDefinition`.
        expected_token: The bearer token callers must present.
        proposal_store: Optional :class:`SqliteProposalStore`; proposal endpoints
            return 503 when ``None``.
        mcp_call: Optional coroutine injected for the approve endpoint; returns 503
            when ``None``.

    Returns:
        A fully configured :class:`FastAPI` application.
    """
    app = FastAPI(title="saga-agents external API")

    def _verify_token(authorization: str | None = Header(default=None)) -> None:
        """FastAPI dependency that enforces bearer-token authentication."""
        expected = f"Bearer {expected_token}"
        if authorization != expected:
            raise HTTPException(status_code=403, detail="Invalid or missing token")

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.post("/triggers/{agent_id}", status_code=202)
    async def trigger_agent(
        agent_id: str,
        _: None = Depends(_verify_token),
    ) -> JSONResponse:
        if agent_id not in definitions:
            raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")
        await executor.submit(RunRequest(agent_id, reason="external"))
        return JSONResponse({"status": "accepted", "agent_id": agent_id}, status_code=202)

    @app.get("/agents/{agent_id}/proposals")
    async def list_proposals(
        agent_id: str,
        _: None = Depends(_verify_token),
    ) -> JSONResponse:
        if proposal_store is None:
            return JSONResponse({"error": "proposals disabled"}, status_code=503)
        records = await proposal_store.list_pending(agent_id)
        return JSONResponse([r.model_dump(mode="json") for r in records])

    @app.post("/proposals/{proposal_id}/approve")
    async def approve_proposal(
        proposal_id: str,
        _: None = Depends(_verify_token),
    ) -> JSONResponse:
        if mcp_call is None:
            return JSONResponse({"error": "proposals disabled"}, status_code=503)
        if proposal_store is None:
            return JSONResponse({"error": "proposals disabled"}, status_code=503)
        record = await proposal_store.get(proposal_id)
        if record is None or record.status != "pending":
            raise HTTPException(status_code=404, detail=f"Proposal not found: {proposal_id}")
        try:
            result = await apply_proposal(record, mcp_call)
        except Exception as exc:  # noqa: BLE001
            await proposal_store.set_status(proposal_id, "failed", error=str(exc))
            return JSONResponse({"error": str(exc)}, status_code=500)
        await proposal_store.set_status(proposal_id, "applied")
        try:
            safe_result = jsonable_encoder(result)
        except Exception:  # noqa: BLE001
            safe_result = str(result)
        return JSONResponse({"status": "applied", "result": safe_result})

    @app.post("/proposals/{proposal_id}/reject")
    async def reject_proposal(
        proposal_id: str,
        _: None = Depends(_verify_token),
    ) -> JSONResponse:
        if proposal_store is None:
            return JSONResponse({"error": "proposals disabled"}, status_code=503)
        record = await proposal_store.get(proposal_id)
        if record is None or record.status != "pending":
            raise HTTPException(status_code=404, detail=f"Proposal not found: {proposal_id}")
        await proposal_store.set_status(proposal_id, "rejected")
        return JSONResponse({"status": "rejected"})

    return app
