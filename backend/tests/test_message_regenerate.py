"""POST regenerate da última resposta do assistente."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from assistente_medico_api.graph.nodes.generate import GENERATE_SYSTEM_PROMPT
from assistente_medico_api.models.conversation import Conversation, ConversationMessage

DR_A_HEADERS = {
    "Accept": "application/json",
    "X-User-Id": "dr-a",
}
SSE_HEADERS = {
    "Accept": "text/event-stream",
    "X-User-Id": "dr-a",
}


class RegenerateDummyGraph:
    """Grafo mínimo para regeneração."""

    def __init__(self):
        self.last_initial = None

    async def aget_state(self, config):
        return SimpleNamespace(values={})

    async def ainvoke(self, initial, config=None):
        self.last_initial = initial
        return {
            "answer": "resposta regenerada",
            "sources": ["fonte-nova"],
            "reasoning_steps": ["passo-novo"],
            "generate_llm_output": "bruto-novo",
        }

    async def astream_events(self, initial, config=None, *, version: str):
        if False:  # pragma: no cover
            yield {}


async def _seed_two_turn_conversation(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    conv_id: str,
    doctor_id: str = "dr-a",
) -> tuple[str, str]:
    """Retorna (id mensagem user, id mensagem assistant)."""
    now = datetime.now(UTC)
    user_id = f"msg-{conv_id}-u"
    assistant_id = f"msg-{conv_id}-a"
    async with session_factory() as session:
        session.add(
            Conversation(
                id=conv_id,
                doctor_id=doctor_id,
                patient_id="p1",
                system_prompt=GENERATE_SYSTEM_PROMPT,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            ConversationMessage(
                id=user_id,
                conversation_id=conv_id,
                author="user",
                content="pergunta um",
                created_at=now,
            )
        )
        session.add(
            ConversationMessage(
                id=assistant_id,
                conversation_id=conv_id,
                author="assistant",
                content="resposta um",
                created_at=now,
            )
        )
        await session.commit()
    return user_id, assistant_id


@pytest.mark.asyncio
async def test_get_messages_hides_superseded_assistant(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    conv_id = "conv-superseded"
    _, assistant_id = await _seed_two_turn_conversation(
        test_session_factory,
        conv_id=conv_id,
    )
    replacement_id = f"msg-{conv_id}-a2"
    now = datetime.now(UTC)
    async with test_session_factory() as session:
        old = (
            await session.execute(
                select(ConversationMessage).where(ConversationMessage.id == assistant_id)
            )
        ).scalar_one()
        session.add(
            ConversationMessage(
                id=replacement_id,
                conversation_id=conv_id,
                author="assistant",
                content="resposta nova",
                created_at=now,
            )
        )
        old.superseded_by_message_id = replacement_id
        session.add(old)
        await session.commit()

    res = await async_client.get(
        f"/api/assistant/conversations/{conv_id}/messages",
        headers=DR_A_HEADERS,
    )
    assert res.status_code == 200
    ids = [m["id"] for m in res.json()["messages"]]
    assert ids == [f"msg-{conv_id}-u", replacement_id]


@pytest.mark.asyncio
async def test_regenerate_replaces_last_assistant_json(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    conv_id = "conv-regen-json"
    _, assistant_id = await _seed_two_turn_conversation(
        test_session_factory,
        conv_id=conv_id,
    )

    dummy = RegenerateDummyGraph()
    app.state.chat_graph = dummy
    res = await async_client.post(
        f"/api/assistant/conversations/{conv_id}/messages/{assistant_id}/regenerate",
        headers=DR_A_HEADERS,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["text"] == "resposta regenerada"
    new_id = body["messageId"]
    assert new_id != assistant_id

    assert dummy.last_initial is not None
    assert dummy.last_initial["query"] == "pergunta um"
    history = dummy.last_initial.get("chat_history") or []
    assert history == []

    get_res = await async_client.get(
        f"/api/assistant/conversations/{conv_id}/messages",
        headers=DR_A_HEADERS,
    )
    messages = get_res.json()["messages"]
    assert len(messages) == 2
    assert messages[1]["id"] == new_id
    assert messages[1]["content"] == "resposta regenerada"

    async with test_session_factory() as session:
        old = (
            await session.execute(
                select(ConversationMessage).where(ConversationMessage.id == assistant_id)
            )
        ).scalar_one()
        assert old.superseded_by_message_id == new_id


@pytest.mark.asyncio
async def test_regenerate_rejects_non_last_assistant(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    conv_id = "conv-regen-not-last"
    now = datetime.now(UTC)
    first_assistant = f"msg-{conv_id}-a1"
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
                id=f"msg-{conv_id}-u1",
                conversation_id=conv_id,
                author="user",
                content="p1",
                created_at=now,
            )
        )
        session.add(
            ConversationMessage(
                id=first_assistant,
                conversation_id=conv_id,
                author="assistant",
                content="r1",
                created_at=now,
            )
        )
        session.add(
            ConversationMessage(
                id=f"msg-{conv_id}-u2",
                conversation_id=conv_id,
                author="user",
                content="p2",
                created_at=now,
            )
        )
        session.add(
            ConversationMessage(
                id=f"msg-{conv_id}-a2",
                conversation_id=conv_id,
                author="assistant",
                content="r2",
                created_at=now,
            )
        )
        await session.commit()

    app.state.chat_graph = RegenerateDummyGraph()
    res = await async_client.post(
        f"/api/assistant/conversations/{conv_id}/messages/{first_assistant}/regenerate",
        headers=DR_A_HEADERS,
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_regenerate_builds_history_from_prior_turns(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    conv_id = "conv-regen-history"
    now = datetime.now(UTC)
    last_assistant = f"msg-{conv_id}-a2"
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
        for author, content, mid in (
            ("user", "pergunta 1", f"msg-{conv_id}-u1"),
            ("assistant", "resposta 1", f"msg-{conv_id}-a1"),
            ("user", "pergunta 2", f"msg-{conv_id}-u2"),
            ("assistant", "resposta 2", last_assistant),
        ):
            session.add(
                ConversationMessage(
                    id=mid,
                    conversation_id=conv_id,
                    author=author,
                    content=content,
                    created_at=now,
                )
            )
        await session.commit()

    dummy = RegenerateDummyGraph()
    app.state.chat_graph = dummy
    res = await async_client.post(
        f"/api/assistant/conversations/{conv_id}/messages/{last_assistant}/regenerate",
        headers=DR_A_HEADERS,
    )
    assert res.status_code == 200
    history = dummy.last_initial.get("chat_history") or []
    assert len(history) == 2
    assert history[0]["content"] == "pergunta 1"
    assert history[1]["content"] == "resposta 1"
    assert dummy.last_initial["query"] == "pergunta 2"
