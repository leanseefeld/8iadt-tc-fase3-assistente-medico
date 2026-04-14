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

    def invoke(self, _initial):
        self.invoke_calls += 1
        raise AssertionError("invoke() should not be called by API paths")

    async def ainvoke(self, _initial):
        self.ainvoke_calls += 1
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

