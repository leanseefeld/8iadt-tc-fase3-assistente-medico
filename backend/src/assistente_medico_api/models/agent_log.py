"""Agent log SQLModel table."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class AgentLogEntry(SQLModel, table=True):
    __tablename__ = "agent_log_entries"

    id: int | None = Field(default=None, primary_key=True)
    patient_id: str = Field(foreign_key="patients.id", index=True)
    step: str
    status: str
    detail: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
