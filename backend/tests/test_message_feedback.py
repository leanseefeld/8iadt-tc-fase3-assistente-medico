"""PATCH de feedback em mensagens do assistente."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from assistente_medico_api.models.conversation import ConversationMessage

CHAT_JSON_HEADERS = {
    "Accept": "application/json",
    "X-User-Id": "dr-test",
}


class PersistDummyGraph:
    """Grafo fake mínimo para persistir turno de chat."""

    async def aget_state(self, config):
        return SimpleNamespace(values={})

    async def ainvoke(self, initial, config=None):
        return {
            "answer": "resposta",
            "sources": [],
            "reasoning_steps": [],
            "generate_llm_output": "bruto",
        }

    async def astream_events(self, initial, config=None, *, version: str):
        if False:  # pragma: no cover
            yield {}


@pytest.mark.asyncio
async def test_patch_message_feedback_positive(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    app.state.chat_graph = PersistDummyGraph()
    chat_res = await async_client.post(
        "/api/assistant/chat",
        headers=CHAT_JSON_HEADERS,
        json={"patientId": "p1", "message": "ola"},
    )
    assert chat_res.status_code == 200
    thread_id = chat_res.json()["threadId"]
    message_id = chat_res.json()["messageId"]

    patch_res = await async_client.patch(
        f"/api/assistant/conversations/{thread_id}/messages/{message_id}",
        headers=CHAT_JSON_HEADERS,
        json={"feedbackRating": "positive"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json() == {
        "messageId": message_id,
        "feedbackRating": "positive",
    }

    async with test_session_factory() as session:
        row = (
            await session.execute(
                select(ConversationMessage).where(ConversationMessage.id == message_id)
            )
        ).scalar_one()
    assert row.feedback_rating == "positive"


@pytest.mark.asyncio
async def test_patch_message_feedback_switch_and_clear(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    app.state.chat_graph = PersistDummyGraph()
    chat_res = await async_client.post(
        "/api/assistant/chat",
        headers=CHAT_JSON_HEADERS,
        json={"patientId": "p1", "message": "ola"},
    )
    thread_id = chat_res.json()["threadId"]
    message_id = chat_res.json()["messageId"]

    await async_client.patch(
        f"/api/assistant/conversations/{thread_id}/messages/{message_id}",
        headers=CHAT_JSON_HEADERS,
        json={"feedbackRating": "positive"},
    )
    switch = await async_client.patch(
        f"/api/assistant/conversations/{thread_id}/messages/{message_id}",
        headers=CHAT_JSON_HEADERS,
        json={"feedbackRating": "negative"},
    )
    assert switch.status_code == 200
    assert switch.json()["feedbackRating"] == "negative"

    cleared = await async_client.patch(
        f"/api/assistant/conversations/{thread_id}/messages/{message_id}",
        headers=CHAT_JSON_HEADERS,
        json={"feedbackRating": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["feedbackRating"] is None

    async with test_session_factory() as session:
        row = (
            await session.execute(
                select(ConversationMessage).where(ConversationMessage.id == message_id)
            )
        ).scalar_one()
    assert row.feedback_rating is None


@pytest.mark.asyncio
async def test_patch_message_feedback_wrong_doctor_forbidden(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
):
    app.state.chat_graph = PersistDummyGraph()
    chat_res = await async_client.post(
        "/api/assistant/chat",
        headers=CHAT_JSON_HEADERS,
        json={"patientId": "p1", "message": "ola"},
    )
    thread_id = chat_res.json()["threadId"]
    message_id = chat_res.json()["messageId"]

    res = await async_client.patch(
        f"/api/assistant/conversations/{thread_id}/messages/{message_id}",
        headers={"Accept": "application/json", "X-User-Id": "outro-medico"},
        json={"feedbackRating": "positive"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_patch_message_feedback_user_message_rejected(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory: async_sessionmaker[AsyncSession],
):
    app.state.chat_graph = PersistDummyGraph()
    chat_res = await async_client.post(
        "/api/assistant/chat",
        headers=CHAT_JSON_HEADERS,
        json={"patientId": "p1", "message": "ola"},
    )
    thread_id = chat_res.json()["threadId"]

    async with test_session_factory() as session:
        user_msg = (
            await session.execute(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == thread_id,
                    ConversationMessage.author == "user",
                )
            )
        ).scalar_one()
        user_id = user_msg.id

    res = await async_client.patch(
        f"/api/assistant/conversations/{thread_id}/messages/{user_id}",
        headers=CHAT_JSON_HEADERS,
        json={"feedbackRating": "positive"},
    )
    assert res.status_code == 400
