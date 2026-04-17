"""Exam SQLModel table."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Exam(SQLModel, table=True):
    __tablename__ = "exams"

    id: str = Field(primary_key=True)
    patient_id: str = Field(foreign_key="patients.id", index=True)
    name: str
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str = Field(default="pending")
    result: str | None = None
    interpretation: str | None = None
    source: str = Field(default="manual")
    protocol_ref: str | None = None
    attachment_name: str | None = None
    attachment_mime: str | None = None
    attachment_size: int | None = None
    attachment_path: str | None = None
