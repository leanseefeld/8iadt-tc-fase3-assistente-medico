"""Repository: conversas do chat com assistente."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from assistente_medico_api.models.conversation import Conversation, ConversationMessage

PREVIEW_MAX_LEN = 80


def _truncate_preview(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= PREVIEW_MAX_LEN:
        return stripped
    return stripped[: PREVIEW_MAX_LEN - 1] + "…"


async def get_conversation_by_id(
    session: AsyncSession,
    conversation_id: str,
) -> Conversation | None:
    statement = select(Conversation).where(Conversation.id == conversation_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def create_conversation(session: AsyncSession, row: Conversation) -> Conversation:
    session.add(row)
    await session.flush()
    return row


async def touch_conversation_updated_at(
    session: AsyncSession,
    conversation: Conversation,
) -> Conversation:
    conversation.updated_at = datetime.now(UTC)
    session.add(conversation)
    await session.flush()
    return conversation


async def create_message(
    session: AsyncSession,
    row: ConversationMessage,
) -> ConversationMessage:
    session.add(row)
    await session.flush()
    return row


async def get_message_by_id(
    session: AsyncSession,
    message_id: str,
) -> ConversationMessage | None:
    statement = select(ConversationMessage).where(ConversationMessage.id == message_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def set_message_feedback(
    session: AsyncSession,
    message: ConversationMessage,
    rating: str | None,
) -> ConversationMessage:
    message.feedback_rating = rating
    session.add(message)
    await session.flush()
    return message


async def list_conversations_by_patient_and_doctor(
    session: AsyncSession,
    *,
    patient_id: str,
    doctor_id: str,
) -> list[Conversation]:
    """Conversas ativas (não arquivadas) do médico para o paciente."""
    statement = (
        select(Conversation)
        .where(Conversation.patient_id == patient_id)
        .where(Conversation.doctor_id == doctor_id)
        .where(col(Conversation.archived_at).is_(None))
        .order_by(col(Conversation.updated_at).desc())
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def fetch_first_user_message_previews(
    session: AsyncSession,
    conversation_ids: list[str],
) -> dict[str, str]:
    """
    Primeira mensagem user por conversa em uma query (evita N+1 na listagem).
    """
    if not conversation_ids:
        return {}

    subq = (
        select(
            ConversationMessage.conversation_id,
            ConversationMessage.content,
            func.row_number()
            .over(
                partition_by=ConversationMessage.conversation_id,
                order_by=ConversationMessage.created_at.asc(),
            )
            .label("rn"),
        )
        .where(ConversationMessage.conversation_id.in_(conversation_ids))
        .where(ConversationMessage.author == "user")
        .subquery()
    )
    statement = select(subq.c.conversation_id, subq.c.content).where(subq.c.rn == 1)
    result = await session.execute(statement)
    return {
        row.conversation_id: _truncate_preview(row.content)
        for row in result.all()
    }


async def list_messages_by_conversation(
    session: AsyncSession,
    conversation_id: str,
) -> list[ConversationMessage]:
    statement = (
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(col(ConversationMessage.created_at).asc())
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def list_active_messages_by_conversation(
    session: AsyncSession,
    conversation_id: str,
) -> list[ConversationMessage]:
    """Mensagens visíveis na UI e usadas no histórico do grafo (não substituídas)."""
    statement = (
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .where(col(ConversationMessage.superseded_by_message_id).is_(None))
        .order_by(col(ConversationMessage.created_at).asc())
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def mark_message_superseded(
    session: AsyncSession,
    message: ConversationMessage,
    *,
    replacement_message_id: str,
) -> ConversationMessage:
    message.superseded_by_message_id = replacement_message_id
    session.add(message)
    await session.flush()
    return message


async def archive_conversation(
    session: AsyncSession,
    conversation: Conversation,
    archived_by: str,
) -> Conversation:
    conversation.archived_at = datetime.now(UTC)
    conversation.archived_by = archived_by.strip()
    session.add(conversation)
    await session.flush()
    return conversation
