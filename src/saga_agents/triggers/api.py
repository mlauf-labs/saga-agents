"""External HTTP API for saga-agents: health check and trigger endpoints."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from saga_agents.config.models import AgentDefinition
from saga_agents.triggers.base import RunRequest
from saga_agents.triggers.executor import RunExecutor


def build_api(
    executor: RunExecutor,
    definitions: dict[str, AgentDefinition],
    *,
    expected_token: str,
    proposal_store: object | None = None,
) -> FastAPI:
    """Construct and return a FastAPI application for the external trigger API.

    Endpoints:
    - ``GET /healthz`` — liveness probe.
    - ``POST /triggers/{agent_id}`` — trigger an agent run externally; requires
      ``Authorization: Bearer <expected_token>`` header.

    Args:
        executor: The :class:`RunExecutor` that dispatches agent runs.
        definitions: Mapping of agent ID to :class:`AgentDefinition`.
        expected_token: The bearer token callers must present.
        proposal_store: Reserved for Task 14 proposal endpoints (unused here).

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

    return app
