"""Pedidos e respostas do endpoint de chat."""

from __future__ import annotations

from datetime import datetime
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
    audit_id: str | None = Field(
        default=None,
        serialization_alias="auditId",
        description="Identificador do registro de auditoria RAG, quando disponível.",
    )
    guardrail_status: str | None = Field(
        default=None,
        serialization_alias="guardrailStatus",
        description="Status do guardrail: safe | warned | blocked | regenerated.",
    )
    guardrail_reason: str | None = Field(
        default=None,
        serialization_alias="guardrailReason",
        description="Motivo da classificação do guardrail.",
    )
    message_id: str | None = Field(
        default=None,
        serialization_alias="messageId",
        description="Id persistido da mensagem do assistente neste turno.",
    )


class MessageFeedbackPatchRequest(BaseModel):
    """Corpo do PATCH de avaliação de mensagem do assistente."""

    model_config = ConfigDict(populate_by_name=True)

    feedback_rating: Literal["positive", "negative"] | None = Field(
        alias="feedbackRating",
        description="positive/negative para avaliar; null remove a avaliação.",
    )


class MessageFeedbackPatchResponse(BaseModel):
    """Resposta após atualizar feedback de uma mensagem."""

    model_config = ConfigDict(populate_by_name=True)

    message_id: str = Field(serialization_alias="messageId")
    feedback_rating: Literal["positive", "negative"] | None = Field(
        serialization_alias="feedbackRating",
    )


class ConversationSummary(BaseModel):
    """Resumo de conversa para listagem no sidebar."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    patient_id: str = Field(serialization_alias="patientId")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    preview: str | None = None


class ConversationListResponse(BaseModel):
    """Lista de conversas não arquivadas do médico logado."""

    model_config = ConfigDict(populate_by_name=True)

    conversations: list[ConversationSummary]


class ConversationMessageResponse(BaseModel):
    """Mensagem persistida para hidratar a UI."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    author: Literal["user", "assistant"]
    content: str
    sources: list[str] | None = None
    reasoning_steps: list[str] | None = Field(
        default=None,
        serialization_alias="reasoningSteps",
    )
    feedback_rating: Literal["positive", "negative"] | None = Field(
        default=None,
        serialization_alias="feedbackRating",
    )
    created_at: datetime = Field(serialization_alias="createdAt")


class ConversationMessagesResponse(BaseModel):
    """Mensagens completas de uma conversa."""

    model_config = ConfigDict(populate_by_name=True)

    conversation_id: str = Field(serialization_alias="conversationId")
    patient_id: str = Field(serialization_alias="patientId")
    messages: list[ConversationMessageResponse]


class ConversationArchiveResponse(BaseModel):
    """Resposta após arquivar conversa."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    archived_at: datetime = Field(serialization_alias="archivedAt")
    archived_by: str = Field(serialization_alias="archivedBy")


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
