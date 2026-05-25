"""Histórico do grafo ignora mensagens substituídas."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assistente_medico_api.graph.nodes.generate import GENERATE_SYSTEM_PROMPT
from assistente_medico_api.models.conversation import Conversation, ConversationMessage
from assistente_medico_api.services import chat_persistence


@pytest.mark.asyncio
async def test_build_chat_history_skips_superseded_messages(
    test_session_factory: async_sessionmaker[AsyncSession],
):
    conv_id = "conv-history-active"
    now = datetime.now(UTC)
    async with test_session_factory() as session:
        session.add(
            Conversation(
                id=conv_id,
                doctor_id="dr-a",
                patient_id="p1",
                system_prompt=GENERATE_SYSTEM_PROMPT,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            ConversationMessage(
                id="u1",
                conversation_id=conv_id,
                author="user",
                content="pergunta",
                created_at=now,
            )
        )
        session.add(
            ConversationMessage(
                id="a-old",
                conversation_id=conv_id,
                author="assistant",
                content="resposta antiga",
                superseded_by_message_id="a-new",
                created_at=now,
            )
        )
        session.add(
            ConversationMessage(
                id="a-new",
                conversation_id=conv_id,
                author="assistant",
                content="resposta nova",
                created_at=now,
            )
        )
        await session.commit()

    async with test_session_factory() as session:
        history = await chat_persistence.build_chat_history_from_db(session, conv_id)

    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["content"] == "resposta nova"
