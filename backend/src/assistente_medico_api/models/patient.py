"""Patient and vital signs SQLModel tables."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class Patient(SQLModel, table=True):
    __tablename__ = "patients"

    id: str = Field(primary_key=True)
    name: str
    age: int
    sex: str
    status: str = Field(default="admitted")
    admitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cid_code: str
    cid_label: str
    observations: str
    comorbidities: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    current_medications: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))


class VitalSigns(SQLModel, table=True):
    __tablename__ = "vital_signs"

    id: int | None = Field(default=None, primary_key=True)
    patient_id: str = Field(foreign_key="patients.id", index=True)
    blood_pressure: str
    temperature: float
    oxygen_saturation: int
    heart_rate: int
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
