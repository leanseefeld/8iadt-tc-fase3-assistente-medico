"""Pedidos e respostas do endpoint de chat."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatHistoryTurnModel(BaseModel):
    """Um turno anterior da conversa (não inclui a mensagem corrente em `message`)."""

    role: Literal["user", "assistant"]
    content: str = Field(
        ...,
        min_length=1,
        max_length=8000,
        description="Texto do turno, sem o prefixo PCDT da última pergunta.",
    )


class ChatRequest(BaseModel):
    """Corpo JSON: camelCase no fio (frontend), normalizado no servidor."""

    model_config = ConfigDict(populate_by_name=True)

    patient_id: str = Field(..., alias="patientId", description="ID do paciente (contexto futuro).")
    message: str = Field(..., min_length=1, description="Última mensagem do médico.")
    thread_id: str | None = Field(
        default=None,
        alias="threadId",
        description="ID da conversa (memória no servidor). Omitir: inicia novo thread.",
    )
    message_history: list[ChatHistoryTurnModel] | None = Field(
        default=None,
        alias="messageHistory",
        max_length=20,
        description="Turnos anteriores (user/assistant) antes da `message` atual.",
    )


class ChatResponseJson(BaseModel):
    """Resposta JSON alinhada ao DTO ChatResponse do frontend."""

    model_config = ConfigDict(populate_by_name=True)

    text: str
    sources: list[str]
    reasoning: list[str]
    thread_id: str = Field(serialization_alias="threadId")


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
