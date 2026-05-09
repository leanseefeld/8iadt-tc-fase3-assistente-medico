"""Schemas for prescription resources (RCE-style payload)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PrescriptionItemSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    medication_name: str = Field(alias="medicationName")
    concentration: str | None = None
    pharmaceutical_form: str | None = Field(default=None, alias="pharmaceuticalForm")
    quantity: str | None = None
    posology: str | None = None

    @field_validator("medication_name", mode="before")
    @classmethod
    def _strip_med(cls, v: str) -> str:
        if isinstance(v, str) and v.strip():
            return v.strip()
        raise ValueError("medicationName é obrigatório")


class PrescriptionCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    patient_cpf: str | None = Field(default=None, alias="patientCpf")
    prescriber_kind: str = Field(default="doctor", alias="prescriberKind")
    prescriber_name: str = Field(alias="prescriberName")
    prescriber_crm: str | None = Field(default=None, alias="prescriberCrm")
    prescriber_crm_uf: str | None = Field(default=None, alias="prescriberCrmUf")
    institution_name: str | None = Field(default=None, alias="institutionName")
    institution_cnpj_cnes: str | None = Field(default=None, alias="institutionCnpjCnes")
    institution_address: str | None = Field(default=None, alias="institutionAddress")
    institution_phone: str | None = Field(default=None, alias="institutionPhone")
    items: list[PrescriptionItemSchema]
    notes: str | None = None
    chat_thread_id: str | None = Field(default=None, alias="chatThreadId")
    decision_flow_run_id: str | None = Field(default=None, alias="decisionFlowRunId")


class PrescriptionArchiveRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reason: str = Field(min_length=5)
    archived_by: str = Field(alias="archivedBy")


class PrescriptionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    patient_id: str = Field(alias="patientId")
    patient_cpf: str | None = Field(alias="patientCpf")
    prescriber_kind: str = Field(alias="prescriberKind")
    prescriber_name: str = Field(alias="prescriberName")
    prescriber_crm: str | None = Field(alias="prescriberCrm")
    prescriber_crm_uf: str | None = Field(alias="prescriberCrmUf")
    institution_name: str | None = Field(alias="institutionName")
    institution_cnpj_cnes: str | None = Field(alias="institutionCnpjCnes")
    institution_address: str | None = Field(alias="institutionAddress")
    institution_phone: str | None = Field(alias="institutionPhone")
    items: list[PrescriptionItemSchema]
    notes: str | None = None
    chat_thread_id: str | None = Field(alias="chatThreadId")
    decision_flow_run_id: str | None = Field(alias="decisionFlowRunId")
    issued_at: datetime = Field(alias="issuedAt")
    archived_at: datetime | None = Field(alias="archivedAt")
    archived_reason: str | None = Field(alias="archivedReason")
    archived_by: str | None = Field(alias="archivedBy")


class PrescriptionListResponse(BaseModel):
    prescriptions: list[PrescriptionResponse]


class SinglePrescriptionResponse(BaseModel):
    prescription: PrescriptionResponse
