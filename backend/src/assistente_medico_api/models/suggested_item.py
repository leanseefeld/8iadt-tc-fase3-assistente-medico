"""Suggested item SQLModel table."""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class SuggestedItem(SQLModel, table=True):
    __tablename__ = "suggested_items"

    id: str = Field(primary_key=True)
    patient_id: str = Field(foreign_key="patients.id", index=True)
    type: str
    description: str
    status: str = Field(default="suggested")
    protocol_ref: str | None = None
