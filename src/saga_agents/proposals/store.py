"""ProposalRecord model, ProposalSink protocol, and SqliteProposalStore implementation."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import aiosqlite
from pydantic import BaseModel

from saga_agents.core.logging import get_logger

log = get_logger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS proposals (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    action      TEXT NOT NULL,
    arguments   TEXT NOT NULL,
    rationale   TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    error       TEXT
)
"""


class ProposalRecord(BaseModel):
    """A single persisted proposal from an agent run."""

    id: str
    agent_id: str
    run_id: str
    action: str
    arguments: dict[str, Any]
    rationale: str
    status: Literal["pending", "applied", "rejected", "failed"]
    created_at: datetime
    error: str | None = None


class ProposalSink(Protocol):
    """Protocol satisfied by any proposal persistence backend."""

    async def add(
        self,
        agent_id: str,
        run_id: str,
        action: str,
        arguments: dict[str, Any],
        rationale: str,
    ) -> ProposalRecord: ...

    async def list_pending(self, agent_id: str | None = None) -> list[ProposalRecord]: ...

    async def get(self, proposal_id: str) -> ProposalRecord | None: ...

    async def set_status(
        self,
        proposal_id: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None: ...


def _row_to_record(row: aiosqlite.Row) -> ProposalRecord:
    """Convert a DB row (tuple) to a :class:`ProposalRecord`."""
    (
        row_id,
        agent_id,
        run_id,
        action,
        arguments_json,
        rationale,
        status,
        created_at_str,
        error,
    ) = row
    return ProposalRecord(
        id=row_id,
        agent_id=agent_id,
        run_id=run_id,
        action=action,
        arguments=json.loads(arguments_json),
        rationale=rationale,
        status=status,
        created_at=datetime.fromisoformat(created_at_str),
        error=error,
    )


class SqliteProposalStore:
    """aiosqlite-backed :class:`ProposalSink` implementation.

    Args:
        db_path: Filesystem path for the SQLite database file.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        """Create the proposals table if it does not already exist."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE)
            await db.commit()
        log.info("proposal_store_initialized", db_path=self._db_path)

    async def add(
        self,
        agent_id: str,
        run_id: str,
        action: str,
        arguments: dict[str, Any],
        rationale: str,
    ) -> ProposalRecord:
        """Persist a new pending proposal and return the stored record.

        Args:
            agent_id: ID of the agent that produced the proposal.
            run_id: Hex run identifier from :class:`AgentRunner`.
            action: MCP tool name to invoke when approved.
            arguments: Keyword arguments for that tool call.
            rationale: Human-readable explanation from the agent.

        Returns:
            The newly created :class:`ProposalRecord` with status ``"pending"``.
        """
        record = ProposalRecord(
            id=uuid.uuid4().hex,
            agent_id=agent_id,
            run_id=run_id,
            action=action,
            arguments=arguments,
            rationale=rationale,
            status="pending",
            created_at=datetime.now(UTC),
            error=None,
        )
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO proposals
                    (id, agent_id, run_id, action, arguments, rationale, status, created_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.agent_id,
                    record.run_id,
                    record.action,
                    json.dumps(record.arguments),
                    record.rationale,
                    record.status,
                    record.created_at.isoformat(),
                    record.error,
                ),
            )
            await db.commit()
        log.info("proposal_added", proposal_id=record.id, agent_id=agent_id, action=action)
        return record

    async def list_pending(self, agent_id: str | None = None) -> list[ProposalRecord]:
        """Return all proposals with status ``"pending"``.

        Args:
            agent_id: If provided, filter to proposals from this agent only.

        Returns:
            List of matching :class:`ProposalRecord` instances, oldest first.
        """
        async with aiosqlite.connect(self._db_path) as db:
            if agent_id is None:
                cursor = await db.execute(
                    "SELECT id, agent_id, run_id, action, arguments, rationale, status,"
                    " created_at, error FROM proposals WHERE status = ? ORDER BY created_at",
                    ("pending",),
                )
            else:
                cursor = await db.execute(
                    "SELECT id, agent_id, run_id, action, arguments, rationale, status,"
                    " created_at, error FROM proposals"
                    " WHERE status = ? AND agent_id = ? ORDER BY created_at",
                    ("pending", agent_id),
                )
            rows = await cursor.fetchall()
        return [_row_to_record(row) for row in rows]

    async def get(self, proposal_id: str) -> ProposalRecord | None:
        """Fetch a single proposal by ID.

        Args:
            proposal_id: UUID hex string of the proposal.

        Returns:
            The :class:`ProposalRecord`, or ``None`` if not found.
        """
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT id, agent_id, run_id, action, arguments, rationale, status,"
                " created_at, error FROM proposals WHERE id = ?",
                (proposal_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_record(row)

    async def set_status(
        self,
        proposal_id: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        """Update the status (and optional error) of a proposal.

        Args:
            proposal_id: UUID hex string of the proposal to update.
            status: New status value (``"applied"``, ``"rejected"``, or ``"failed"``).
            error: Optional error message to store alongside the status change.
        """
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "UPDATE proposals SET status = ?, error = ? WHERE id = ?",
                (status, error, proposal_id),
            )
            await db.commit()
        if cursor.rowcount == 0:
            log.warning("proposal_status_update_no_match", proposal_id=proposal_id, status=status)
        else:
            log.info("proposal_status_updated", proposal_id=proposal_id, status=status)
