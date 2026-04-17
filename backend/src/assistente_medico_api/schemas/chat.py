"""Pedidos e respostas do endpoint de chat."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """Corpo JSON: camelCase no fio (frontend), normalizado no servidor."""

    model_config = ConfigDict(populate_by_name=True)

    patient_id: str = Field(..., alias="patientId", description="ID do paciente (contexto futuro).")
    message: str = Field(..., min_length=1, description="Última mensagem do médico.")


class ChatResponseJson(BaseModel):
    """Resposta JSON alinhada ao DTO ChatResponse do frontend."""

    text: str
    sources: list[str]
    reasoning: list[str]


class DecisionFlowRequest(BaseModel):
    """Corpo JSON para simulacao de fluxo de decisao por paciente."""

    model_config = ConfigDict(populate_by_name=True)

    patient_id: str = Field(
        ...,
        alias="patientId",
        description="ID do paciente para compor o fluxo de decisao.",
    )


class DecisionFlowMeta(BaseModel):
    """Metadados de branch do fluxo de decisao."""

    model_config = ConfigDict(populate_by_name=True)

    sepsis_critical: bool = Field(alias="sepsisCritical")
    pharmacy_interaction: bool = Field(alias="pharmacyInteraction")


class DecisionFlowResponse(BaseModel):
    """Resposta textual do fluxo de decisao do assistente."""

    lines: list[str]
    meta: DecisionFlowMeta
