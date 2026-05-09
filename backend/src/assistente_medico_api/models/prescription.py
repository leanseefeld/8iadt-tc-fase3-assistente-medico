"""Prescription SQLModel table (Receita de Controle Especial — layout protótipo)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class Prescription(SQLModel, table=True):
    __tablename__ = "prescriptions"

    id: str = Field(default_factory=lambda: f"px-{uuid4()}", primary_key=True)
    patient_id: str = Field(foreign_key="patients.id", index=True)

    patient_cpf: str | None = None

    # doctor | ai_assistant
    prescriber_kind: str = Field(default="doctor")
    prescriber_name: str
    prescriber_crm: str | None = None
    prescriber_crm_uf: str | None = None
    institution_name: str | None = None
    institution_cnpj_cnes: str | None = None
    institution_address: str | None = None
    institution_phone: str | None = None

    items: list[dict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    notes: str | None = None

    chat_thread_id: str | None = Field(default=None, index=True)
    decision_flow_run_id: str | None = None

    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)

    archived_at: datetime | None = Field(default=None, index=True)
    archived_reason: str | None = None
    archived_by: str | None = None
