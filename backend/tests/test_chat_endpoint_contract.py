import json

import pytest
from fastapi import FastAPI
import httpx

from assistente_medico_api.main import create_app


class DummyGraph:
    def __init__(self):
        self.invoke_calls = 0
        self.ainvoke_calls = 0
        self.astream_events_calls = 0
        self.last_initial = None

    def invoke(self, _initial):
        self.invoke_calls += 1
        raise AssertionError("invoke() should not be called by API paths")

    async def ainvoke(self, initial):
        self.ainvoke_calls += 1
        self.last_initial = initial
        return {
            "answer": "ok-json",
            "sources": ["S1"],
            "reasoning_steps": ["R1"],
        }

    async def astream_events(self, _initial, *, version: str):
        self.astream_events_calls += 1
        assert version == "v2"
        if False:  # pragma: no cover
            yield {}
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_post_chat_json_uses_ainvoke_not_invoke():
    app: FastAPI = create_app()
    dummy = DummyGraph()
    app.state.chat_graph = dummy

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/assistant/chat",
            headers={"Accept": "application/json"},
            json={"patientId": "p1", "message": "hi"},
        )

    assert res.status_code == 200
    payload = res.json()
    assert payload["text"] == "ok-json"
    assert payload["sources"] == ["S1"]
    assert payload["reasoning"] == ["R1"]
    assert dummy.ainvoke_calls == 1
    assert dummy.invoke_calls == 0
    assert dummy.last_initial.get("chat_history") == []


@pytest.mark.asyncio
async def test_post_chat_json_pushes_message_history_into_graph_state():
    app: FastAPI = create_app()
    dummy = DummyGraph()
    app.state.chat_graph = dummy

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/assistant/chat",
            headers={"Accept": "application/json"},
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


@pytest.mark.asyncio
async def test_post_chat_sse_error_event_then_ends():
    app: FastAPI = create_app()
    dummy = DummyGraph()
    app.state.chat_graph = dummy

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/assistant/chat",
            headers={"Accept": "text/event-stream"},
            json={"patientId": "p1", "message": "hi"},
        )

    assert res.status_code == 200
    text = res.text
    # SSE payload should include an error event.
    assert "event: error" in text
    # And must not hang: response fully materialized.
    assert text.strip().endswith("}")

    # Parse last data line for the error event.
    # sse-starlette formats as `event: ...` and `data: ...`
    data_lines = [ln for ln in text.splitlines() if ln.startswith("data: ")]
    assert data_lines, text
    last = data_lines[-1].removeprefix("data: ").strip()
    obj = json.loads(last)
    assert "detail" in obj
    assert "boom" in obj["detail"]

