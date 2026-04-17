"""Alert SQLModel table."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"

    id: str = Field(primary_key=True)
    patient_id: str = Field(index=True)
    severity: str = Field(default="info")  # critical, moderate, info
    category: str = Field(default="clinical")  # exam, medication, clinical, system
    message: str
    team: str = Field(default="all")  # doctors, nursing, pharmacy, all
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    resolved: bool = Field(default=False, index=True)
