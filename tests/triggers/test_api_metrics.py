from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from saga_agents.triggers.api import build_api


def _client() -> TestClient:
    executor = MagicMock()
    api = build_api(executor, {}, expected_token="t", proposal_store=None, mcp_call=None)
    return TestClient(api)


def test_metrics_unauthed() -> None:
    r = _client().get("/metrics")
    assert r.status_code == 200
    assert "saga_agent_runs_total" in r.text or "saga_agent_inflight" in r.text


def test_stats_requires_token() -> None:
    assert _client().get("/stats").status_code == 403


def test_stats_with_token() -> None:
    r = _client().get("/stats", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    assert "runtime" in r.json()
