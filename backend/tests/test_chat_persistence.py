"""Persistência de conversas no POST /assistant/chat."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from assistente_medico_api.graph.nodes.generate import GENERATE_SYSTEM_PROMPT
from assistente_medico_api.main import create_app
from assistente_medico_api.models.conversation import Conversation, ConversationMessage
CHAT_JSON_HEADERS = {
    "Accept": "application/json",
    "X-User-Id": "dr-test",
}


class PersistDummyGraph:
    """Grafo fake que devolve estado completo para persistência."""

    def __init__(self, *, checkpoint_history: bool = False):
        self.checkpoint_history = checkpoint_history
        self.last_config = None
        self.last_initial = None

    async def aget_state(self, config):
        self.last_config = config
        values: dict = {}
        if self.checkpoint_history:
            values["chat_history"] = [{"role": "user", "content": "persistido"}]
        return SimpleNamespace(values=values)

    async def ainvoke(self, initial, config=None):
        self.last_initial = initial
        self.last_config = config
        return {
            "answer": "resposta-final",
            "sources": ["[1] PCDT — secao"],
            "reasoning_steps": ["R1", "Guardrail: seguro"],
            "generate_llm_input": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "pergunta"},
            ],
            "generate_llm_output": "resposta-bruta",
            "guardrail_status": "safe",
        }

    async def astream_events(self, initial, config=None, *, version: str):
        if False:  # pragma: no cover
            yield {}


@pytest.mark.asyncio
async def test_chat_persists_conversation_and_messages_on_first_turn(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    app.state.chat_graph = PersistDummyGraph()
    res = await async_client.post(
        "/api/assistant/chat",
        headers=CHAT_JSON_HEADERS,
        json={"patientId": "p1", "message": "ola"},
    )
    assert res.status_code == 200
    thread_id = res.json()["threadId"]

    async with test_session_factory() as session:
        conv = (
            await session.execute(
                select(Conversation).where(Conversation.id == thread_id)
            )
        ).scalar_one()
        assert conv.doctor_id == "dr-test"
        assert conv.patient_id == "p1"
        assert conv.system_prompt == GENERATE_SYSTEM_PROMPT

        messages = list(
            (
                await session.execute(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == thread_id)
                    .order_by(ConversationMessage.created_at)
                )
            ).scalars()
        )
    assert len(messages) == 2
    assert messages[0].author == "user"
    assert messages[0].content == "ola"
    assert messages[0].llm_input is None
    assert messages[1].author == "assistant"
    assert messages[1].content == "resposta-final"
    assert messages[1].llm_output == "resposta-bruta"
    assert messages[1].llm_input[0]["role"] == "system"
    assert messages[1].sources == ["[1] PCDT — secao"]
    assert messages[1].guardrail_status == "safe"


@pytest.mark.asyncio
async def test_chat_multi_turn_appends_four_messages(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    app.state.chat_graph = PersistDummyGraph()
    r1 = await async_client.post(
        "/api/assistant/chat",
        headers=CHAT_JSON_HEADERS,
        json={"patientId": "p1", "message": "t1"},
    )
    thread_id = r1.json()["threadId"]

    await async_client.post(
        "/api/assistant/chat",
        headers=CHAT_JSON_HEADERS,
        json={"patientId": "p1", "message": "t2", "threadId": thread_id},
    )

    async with test_session_factory() as session:
        convs = list((await session.execute(select(Conversation))).scalars())
        msgs = list(
            (
                await session.execute(
                    select(ConversationMessage).where(
                        ConversationMessage.conversation_id == thread_id
                    )
                )
            ).scalars()
        )
    assert len(convs) == 1
    assert len(msgs) == 4


@pytest.mark.asyncio
async def test_chat_requires_x_user_id(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
):
    app.state.chat_graph = PersistDummyGraph()
    res = await async_client.post(
        "/api/assistant/chat",
        headers={"Accept": "application/json"},
        json={"patientId": "p1", "message": "hi"},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_chat_unknown_thread_id_returns_404(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
):
    app.state.chat_graph = PersistDummyGraph()
    res = await async_client.post(
        "/api/assistant/chat",
        headers=CHAT_JSON_HEADERS,
        json={
            "patientId": "p1",
            "message": "hi",
            "threadId": "nao-existe",
        },
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_chat_existing_thread_with_checkpoint(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    async with test_session_factory() as session:
        session.add(
            Conversation(
                id="thread-fixo",
                doctor_id="dr-test",
                patient_id="p1",
                system_prompt=GENERATE_SYSTEM_PROMPT,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()

    dummy = PersistDummyGraph(checkpoint_history=True)
    app.state.chat_graph = dummy
    res = await async_client.post(
        "/api/assistant/chat",
        headers=CHAT_JSON_HEADERS,
        json={
            "patientId": "p1",
            "threadId": "thread-fixo",
            "message": "follow-up",
            "messageHistory": [{"role": "user", "content": "ignorado"}],
        },
    )
    assert res.status_code == 200
    assert dummy.last_initial is not None
    assert "chat_history" not in dummy.last_initial
