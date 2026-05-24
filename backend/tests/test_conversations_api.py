"""GET/PATCH de conversas persistidas do chat."""

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
DR_B_HEADERS = {
    "Accept": "application/json",
    "X-User-Id": "dr-b",
}


class PersistDummyGraph:
    """Grafo fake mínimo para persistir turno de chat."""

    def __init__(self, *, checkpoint_history: bool = False):
        self.checkpoint_history = checkpoint_history
        self.last_initial = None

    async def aget_state(self, config):
        values: dict = {}
        if self.checkpoint_history:
            values["chat_history"] = [{"role": "user", "content": "checkpoint"}]
        return SimpleNamespace(values=values)

    async def ainvoke(self, initial, config=None):
        self.last_initial = initial
        return {
            "answer": "resposta",
            "sources": ["fonte-1"],
            "reasoning_steps": ["passo-1"],
            "generate_llm_output": "bruto",
        }

    async def astream_events(self, initial, config=None, *, version: str):
        if False:  # pragma: no cover
            yield {}


async def _seed_conversation(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    conv_id: str,
    doctor_id: str,
    patient_id: str = "p1",
    user_content: str = "primeira pergunta",
    assistant_content: str = "primeira resposta",
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add(
            Conversation(
                id=conv_id,
                doctor_id=doctor_id,
                patient_id=patient_id,
                system_prompt=GENERATE_SYSTEM_PROMPT,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            ConversationMessage(
                id=f"msg-{conv_id}-u",
                conversation_id=conv_id,
                author="user",
                content=user_content,
                created_at=now,
            )
        )
        session.add(
            ConversationMessage(
                id=f"msg-{conv_id}-a",
                conversation_id=conv_id,
                author="assistant",
                content=assistant_content,
                sources=["fonte"],
                reasoning_steps=["raciocinio"],
                feedback_rating="positive",
                created_at=now,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_list_conversations_filters_by_doctor(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    await _seed_conversation(test_session_factory, conv_id="conv-a", doctor_id="dr-a")
    await _seed_conversation(test_session_factory, conv_id="conv-b", doctor_id="dr-b")

    res_a = await async_client.get(
        "/api/assistant/conversations",
        params={"patientId": "p1"},
        headers=DR_A_HEADERS,
    )
    assert res_a.status_code == 200
    ids_a = {c["id"] for c in res_a.json()["conversations"]}
    assert ids_a == {"conv-a"}

    res_b = await async_client.get(
        "/api/assistant/conversations",
        params={"patientId": "p1"},
        headers=DR_B_HEADERS,
    )
    assert res_b.status_code == 200
    ids_b = {c["id"] for c in res_b.json()["conversations"]}
    assert ids_b == {"conv-b"}


@pytest.mark.asyncio
async def test_list_conversations_includes_preview(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    await _seed_conversation(
        test_session_factory,
        conv_id="conv-preview",
        doctor_id="dr-a",
        user_content="Como tratar febre alta?",
    )
    res = await async_client.get(
        "/api/assistant/conversations",
        params={"patientId": "p1"},
        headers=DR_A_HEADERS,
    )
    assert res.status_code == 200
    conv = res.json()["conversations"][0]
    assert conv["preview"] == "Como tratar febre alta?"


@pytest.mark.asyncio
async def test_list_conversations_excludes_archived(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    await _seed_conversation(test_session_factory, conv_id="conv-active", doctor_id="dr-a")
    await _seed_conversation(test_session_factory, conv_id="conv-archived", doctor_id="dr-a")

    archive_res = await async_client.patch(
        "/api/assistant/conversations/conv-archived/archive",
        headers=DR_A_HEADERS,
    )
    assert archive_res.status_code == 200

    res = await async_client.get(
        "/api/assistant/conversations",
        params={"patientId": "p1"},
        headers=DR_A_HEADERS,
    )
    ids = {c["id"] for c in res.json()["conversations"]}
    assert ids == {"conv-active"}


@pytest.mark.asyncio
async def test_get_conversation_messages(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    await _seed_conversation(test_session_factory, conv_id="conv-msgs", doctor_id="dr-a")

    res = await async_client.get(
        "/api/assistant/conversations/conv-msgs/messages",
        headers=DR_A_HEADERS,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["conversationId"] == "conv-msgs"
    assert len(body["messages"]) == 2
    assert body["messages"][0]["author"] == "user"
    assert body["messages"][1]["author"] == "assistant"
    assert body["messages"][1]["sources"] == ["fonte"]
    assert body["messages"][1]["feedbackRating"] == "positive"


@pytest.mark.asyncio
async def test_get_messages_forbidden_for_other_doctor(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    await _seed_conversation(test_session_factory, conv_id="conv-private", doctor_id="dr-a")
    res = await async_client.get(
        "/api/assistant/conversations/conv-private/messages",
        headers=DR_B_HEADERS,
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_archive_conversation(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    await _seed_conversation(test_session_factory, conv_id="conv-archive", doctor_id="dr-a")

    res = await async_client.patch(
        "/api/assistant/conversations/conv-archive/archive",
        headers=DR_A_HEADERS,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "conv-archive"
    assert body["archivedBy"] == "dr-a"
    assert body["archivedAt"]

    async with test_session_factory() as session:
        row = (
            await session.execute(
                select(Conversation).where(Conversation.id == "conv-archive")
            )
        ).scalar_one()
    assert row.archived_at is not None
    assert row.archived_by == "dr-a"


@pytest.mark.asyncio
async def test_archive_conversation_idempotent_409(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    await _seed_conversation(test_session_factory, conv_id="conv-twice", doctor_id="dr-a")

    first = await async_client.patch(
        "/api/assistant/conversations/conv-twice/archive",
        headers=DR_A_HEADERS,
    )
    assert first.status_code == 200

    second = await async_client.patch(
        "/api/assistant/conversations/conv-twice/archive",
        headers=DR_A_HEADERS,
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_archived_conversation_blocks_get_messages_and_post(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    await _seed_conversation(test_session_factory, conv_id="conv-blocked", doctor_id="dr-a")
    await async_client.patch(
        "/api/assistant/conversations/conv-blocked/archive",
        headers=DR_A_HEADERS,
    )

    get_res = await async_client.get(
        "/api/assistant/conversations/conv-blocked/messages",
        headers=DR_A_HEADERS,
    )
    assert get_res.status_code == 410

    app.state.chat_graph = PersistDummyGraph()
    post_res = await async_client.post(
        "/api/assistant/chat",
        headers=DR_A_HEADERS,
        json={
            "patientId": "p1",
            "message": "continuar",
            "threadId": "conv-blocked",
        },
    )
    assert post_res.status_code == 410


@pytest.mark.asyncio
async def test_resumed_thread_hydrates_chat_history_from_db(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    await _seed_conversation(
        test_session_factory,
        conv_id="conv-resume",
        doctor_id="dr-a",
        user_content="pergunta anterior",
        assistant_content="resposta anterior",
    )

    dummy = PersistDummyGraph(checkpoint_history=False)
    app.state.chat_graph = dummy
    res = await async_client.post(
        "/api/assistant/chat",
        headers=DR_A_HEADERS,
        json={
            "patientId": "p1",
            "message": "nova pergunta",
            "threadId": "conv-resume",
        },
    )
    assert res.status_code == 200
    assert dummy.last_initial is not None
    history = dummy.last_initial.get("chat_history") or []
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "pergunta anterior"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "resposta anterior"
