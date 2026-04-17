"""Schemas for alert resources."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Alert(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    patient_id: str = Field(alias="patientId")
    severity: str  # critical, moderate, info
    category: str  # exam, medication, clinical, system
    message: str
    team: str  # doctors, nursing, pharmacy, all
    created_at: datetime = Field(alias="createdAt")
    resolved: bool


class AlertCreateRequest(BaseModel):
    patient_id: str = Field(alias="patientId")
    severity: str = Field(default="info")
    category: str = Field(default="clinical")
    message: str
    team: str = Field(default="all")


class AlertPatchRequest(BaseModel):
    resolved: bool | None = None


class AlertListResponse(BaseModel):
    alerts: list[Alert]


class AlertResponse(BaseModel):
    alert: Alert
