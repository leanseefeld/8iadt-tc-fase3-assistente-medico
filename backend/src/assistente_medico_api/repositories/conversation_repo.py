"""Repository: conversas do chat com assistente."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from assistente_medico_api.models.conversation import Conversation, ConversationMessage


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
