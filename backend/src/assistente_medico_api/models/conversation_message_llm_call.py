"""Chamadas auxiliares ao LLM de chat por mensagem do assistente (SFT/auditoria)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, JSON, Text
from sqlmodel import Field, SQLModel


class ConversationMessageLlmCall(SQLModel, table=True):
    """Uma invocação auxiliar de MEDICO_LLM_CHAT_MODEL ligada à resposta do assistente."""

    __tablename__ = "conversation_message_llm_calls"

    id: str = Field(default_factory=lambda: f"llmcall-{uuid4()}", primary_key=True)
    assistant_message_id: str = Field(
        foreign_key="conversation_messages.id",
        index=True,
    )
    call_type: str = Field(index=True)
    sequence: int = Field(default=0)
    model: str = Field()
    llm_input: list[dict] = Field(sa_column=Column(JSON, nullable=False))
    llm_output: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
