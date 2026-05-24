"""Conversas do chat com assistente e mensagens persistidas."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, JSON, Text
from sqlmodel import Field, SQLModel


class Conversation(SQLModel, table=True):
    """Sessão de chat entre médico e paciente (id = threadId do cliente)."""

    __tablename__ = "conversations"

    id: str = Field(primary_key=True)
    doctor_id: str = Field(index=True)
    patient_id: str = Field(foreign_key="patients.id", index=True)
    system_prompt: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)


class ConversationMessage(SQLModel, table=True):
    """Mensagem de um turno (médico ou assistente)."""

    __tablename__ = "conversation_messages"

    id: str = Field(default_factory=lambda: f"msg-{uuid4()}", primary_key=True)
    conversation_id: str = Field(foreign_key="conversations.id", index=True)
    author: str = Field(index=True)  # user | assistant
    content: str = Field(sa_column=Column(Text, nullable=False))
    reasoning_steps: list[str] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    sources: list[str] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    llm_input: list[dict] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    llm_output: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    feedback_rating: str | None = Field(default=None, index=True)  # positive | negative
    guardrail_status: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
