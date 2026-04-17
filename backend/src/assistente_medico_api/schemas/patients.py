"""Schemas for patient resources."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from assistente_medico_api.schemas.cids import Cid
from assistente_medico_api.schemas.exams import Exam
from assistente_medico_api.schemas.suggested_items import SuggestedItem


class VitalSigns(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    blood_pressure: str = Field(alias="bloodPressure")
    temperature: float
    oxygen_saturation: int = Field(alias="oxygenSaturation")
    heart_rate: int = Field(alias="heartRate")
    updated_at: datetime = Field(alias="updatedAt")


class AgentLogEntry(BaseModel):
    step: str
    status: str
    detail: str
    timestamp: datetime


class Patient(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    age: int
    sex: str
    status: str
    admitted_at: datetime = Field(alias="admittedAt")
    cid: Cid
    observations: str
    comorbidities: list[str]
    current_medications: list[str] = Field(alias="currentMedications")
    vital_signs: VitalSigns = Field(alias="vitalSigns")
    exams: list[Exam]
    suggested_items: list[SuggestedItem] = Field(alias="suggestedItems")
    agent_log: list[AgentLogEntry] = Field(alias="agentLog")


class PatientCreateRequest(BaseModel):
    name: str | None = None
    age: int | None = None
    sex: str | None = None
    cid: Cid
    observations: str | None = None
    comorbidities: list[str] | None = None
    current_medications: str | None = Field(default=None, alias="currentMedications")


class PatientPatchRequest(BaseModel):
    name: str | None = None
    age: int | None = None
    sex: str | None = None
    status: str | None = None
    cid: Cid | None = None
    observations: str | None = None
    comorbidities: list[str] | None = None
    current_medications: list[str] | None = Field(default=None, alias="currentMedications")


class VitalSignsPatchRequest(BaseModel):
    blood_pressure: str | None = Field(default=None, alias="bloodPressure")
    temperature: float | None = None
    oxygen_saturation: int | None = Field(default=None, alias="oxygenSaturation")
    heart_rate: int | None = Field(default=None, alias="heartRate")


class PatientListResponse(BaseModel):
    patients: list[Patient]


class PatientResponse(BaseModel):
    patient: Patient
