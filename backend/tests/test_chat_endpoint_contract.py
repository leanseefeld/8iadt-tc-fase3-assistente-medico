import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
import httpx

from assistente_medico_api.main import create_app

CHAT_JSON_HEADERS = {
    "Accept": "application/json",
    "X-User-Id": "dr-contract",
}


class DummyGraph:
    def __init__(self):
        self.invoke_calls = 0
        self.ainvoke_calls = 0
        self.astream_events_calls = 0
        self.last_initial = None
        self.last_config = None
        self.last_stream_config = None

    def invoke(self, _initial):
        self.invoke_calls += 1
        raise AssertionError("invoke() should not be called by API paths")

    async def aget_state(self, config):
        """Simula thread novo (sem histórico persistido no checkpointer)."""
        self.last_config = config
        return SimpleNamespace(values={})

    async def ainvoke(self, initial, config=None):
        self.ainvoke_calls += 1
        self.last_initial = initial
        self.last_config = config
        return {
            "answer": "ok-json",
            "sources": ["S1"],
            "reasoning_steps": ["R1"],
            "generate_llm_output": "ok-json",
        }

    async def astream_events(self, initial, config=None, *, version: str):
        self.astream_events_calls += 1
        self.last_stream_initial = initial
        self.last_stream_config = config
        assert version == "v2"
        if False:  # pragma: no cover
            yield {}
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_post_chat_json_uses_ainvoke_not_invoke(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
):
    dummy = DummyGraph()
    app.state.chat_graph = dummy

    res = await async_client.post(
        "/api/assistant/chat",
        headers=CHAT_JSON_HEADERS,
        json={"patientId": "p1", "message": "hi"},
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["text"] == "ok-json"
    assert payload["sources"] == ["S1"]
    assert payload["reasoning"] == ["R1"]
    assert "threadId" in payload and payload["threadId"]
    assert payload["messageId"].startswith("msg-")
    assert dummy.ainvoke_calls == 1
    assert dummy.invoke_calls == 0
    assert dummy.last_initial.get("chat_history") == []
    assert dummy.last_config == {
        "configurable": {"thread_id": payload["threadId"]},
    }


@pytest.mark.asyncio
async def test_post_chat_json_pushes_message_history_into_graph_state(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
):
    dummy = DummyGraph()
    app.state.chat_graph = dummy

    res = await async_client.post(
        "/api/assistant/chat",
        headers=CHAT_JSON_HEADERS,
        json={
            "patientId": "p1",
            "message": "follow-up",
            "messageHistory": [
                {"role": "user", "content": "o que é X?"},
                {"role": "assistant", "content": "X é ..."},
            ],
        },
    )

    assert res.status_code == 200
    assert dummy.ainvoke_calls == 1
    h = dummy.last_initial.get("chat_history") or []
    assert len(h) == 2
    assert h[0] == {"role": "user", "content": "o que é X?"}
    assert h[1] == {"role": "assistant", "content": "X é ..."}


class DummyGraphWithCheckpointHistory(DummyGraph):
    """Simula thread com histórico já no checkpointer LangGraph."""

    async def aget_state(self, config):
        self.last_config = config
        return SimpleNamespace(
            values={
                "chat_history": [{"role": "user", "content": "persistido"}],
            }
        )


@pytest.mark.asyncio
async def test_post_chat_json_omits_chat_history_when_checkpoint_has_it(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
    test_session_factory,
):
    """Com histórico persistido, o update não reenvia `chat_history` (merge no grafo)."""
    from datetime import UTC, datetime

    from assistente_medico_api.graph.nodes.generate import GENERATE_SYSTEM_PROMPT
    from assistente_medico_api.models.conversation import Conversation

    async with test_session_factory() as session:
        session.add(
            Conversation(
                id="thread-fixo",
                doctor_id="dr-contract",
                patient_id="p1",
                system_prompt=GENERATE_SYSTEM_PROMPT,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()

    dummy = DummyGraphWithCheckpointHistory()
    app.state.chat_graph = dummy

    res = await async_client.post(
        "/api/assistant/chat",
        headers=CHAT_JSON_HEADERS,
        json={
            "patientId": "p1",
            "threadId": "thread-fixo",
            "message": "follow-up",
            "messageHistory": [
                {"role": "user", "content": "isto deve ser ignorado"},
            ],
        },
    )

    assert res.status_code == 200
    assert "chat_history" not in dummy.last_initial
    assert dummy.last_config == {
        "configurable": {"thread_id": "thread-fixo"},
    }


@pytest.mark.asyncio
async def test_post_chat_sse_error_event_then_ends(
    app: FastAPI,
    async_client: httpx.AsyncClient,
    chat_patient,
):
    dummy = DummyGraph()
    app.state.chat_graph = dummy

    res = await async_client.post(
        "/api/assistant/chat",
        headers={
            "Accept": "text/event-stream",
            "X-User-Id": "dr-contract",
        },
        json={"patientId": "p1", "message": "hi"},
    )

    assert res.status_code == 200
    text = res.text
    assert "event: error" in text
    assert text.strip().endswith("}")

    data_lines = [ln for ln in text.splitlines() if ln.startswith("data: ")]
    assert data_lines, text
    last = data_lines[-1].removeprefix("data: ").strip()
    obj = json.loads(last)
    assert "detail" in obj
    assert "boom" in obj["detail"]
