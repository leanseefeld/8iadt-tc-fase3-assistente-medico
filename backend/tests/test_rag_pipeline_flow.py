from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI

from assistente_medico_api.deps import get_session
from assistente_medico_api.main import create_app


def _make_app_with_graph(graph):
    """Creates app with graph set and DB/persistence layer mocked out."""
    app: FastAPI = create_app()
    app.state.chat_graph = graph

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    async def _mock_get_session():
        yield mock_session

    app.dependency_overrides[get_session] = _mock_get_session
    return app


def _persistence_patches():
    """Context manager that stubs resolve_conversation and append_turn."""
    fake_conv = MagicMock()
    fake_conv.id = "conv-test"

    resolve = patch(
        "assistente_medico_api.api.chat.chat_persistence.resolve_conversation",
        new_callable=AsyncMock,
        return_value=(fake_conv, "thread-test"),
    )
    append = patch(
        "assistente_medico_api.api.chat.chat_persistence.append_turn",
        new_callable=AsyncMock,
        return_value="msg-test",
    )
    return resolve, append


class _SseGraph:
    def __init__(self, *, final_text: str, sources: list[str], guardrail_status: str = "safe"):
        self.final_text = final_text
        self.sources = sources
        self.guardrail_status = guardrail_status
        self.ainvoke_calls = 0
        self.astream_events_calls = 0

    async def aget_state(self, _config):
        return type("Snap", (), {"values": {}})()

    async def ainvoke(self, *_args, **_kwargs):
        self.ainvoke_calls += 1
        return {
            "answer": self.final_text,
            "sources": self.sources,
            "reasoning_steps": ["R1"],
            "guardrail_status": self.guardrail_status,
            "guardrail_reason": "ok",
        }

    async def astream_events(self, *_args, **_kwargs):
        self.astream_events_calls += 1
        yield {
            "event": "on_chain_end",
            "name": "rerank",
            "data": {
                "output": {
                    "sources": self.sources,
                    "reasoning_steps": ["Busca concluída"],
                    "retrieved_docs": [],
                }
            },
        }
        yield {
            "event": "on_chat_model_stream",
            "name": "ChatOllama",
            "metadata": {"langgraph_node": "generate"},
            "data": {"chunk": type("Chunk", (), {"content": self.final_text[:8]})()},
        }
        yield {
            "event": "on_chain_end",
            "name": "generate",
            "data": {"output": {"answer": self.final_text, "generation_mode": "grounded_answer"}},
        }
        yield {
            "event": "on_chain_end",
            "name": "guardrail",
            "data": {
                "output": {
                    "answer": self.final_text,
                    "guardrail_status": self.guardrail_status,
                    "guardrail_reason": "ok",
                    "audit_id": "audit-1",
                }
            },
        }


class _InsufficientGraph(_SseGraph):
    async def astream_events(self, *_args, **_kwargs):
        self.astream_events_calls += 1
        yield {
            "event": "on_chain_end",
            "name": "rerank",
            "data": {
                "output": {
                    "sources": [],
                    "reasoning_steps": ["Contexto insuficiente"],
                    "retrieved_docs": [],
                }
            },
        }
        yield {
            "event": "on_chain_end",
            "name": "generate",
            "data": {"output": {"answer": self.final_text, "generation_mode": "insufficient_context"}},
        }
        yield {
            "event": "on_chain_end",
            "name": "guardrail",
            "data": {
                "output": {
                    "answer": self.final_text,
                    "guardrail_status": "safe",
                    "guardrail_reason": "ok",
                    "audit_id": "audit-2",
                }
            },
        }


@pytest.mark.asyncio
async def test_post_chat_json_uses_ainvoke_not_invoke():
    dummy = _SseGraph(final_text="ok-json", sources=["[1] PCDT SGB"], guardrail_status="safe")
    app = _make_app_with_graph(dummy)
    resolve_patch, append_patch = _persistence_patches()

    with resolve_patch, append_patch:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                "/api/assistant/chat",
                headers={"Accept": "application/json", "X-User-Id": "test-doctor"},
                json={"patientId": "p1", "message": "hi"},
            )

    assert res.status_code == 200
    payload = res.json()
    assert payload["text"] == "ok-json"
    assert payload["sources"] == ["[1] PCDT SGB"]
    assert payload["reasoning"] == ["R1"]
    assert "threadId" in payload and payload["threadId"]
    assert dummy.ainvoke_calls == 1
    assert dummy.astream_events_calls == 0


@pytest.mark.asyncio
async def test_post_chat_sse_emits_final_event_and_sources():
    dummy = _SseGraph(
        final_text="Resposta baseada em SGB e critérios de inclusão.",
        sources=["[1] PCDT Síndrome de Guillain-Barré - CRITÉRIOS DE INCLUSÃO"],
    )
    app = _make_app_with_graph(dummy)
    resolve_patch, append_patch = _persistence_patches()

    with resolve_patch, append_patch:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                "/api/assistant/chat",
                headers={"Accept": "text/event-stream", "X-User-Id": "test-doctor"},
                json={"patientId": "p1", "message": "Quais são os critérios de inclusão para sgb?"},
            )

    assert res.status_code == 200
    text = res.text
    assert "event: token" in text
    assert "event: final" in text
    assert "event: done" in text

    lines = text.splitlines()
    final_index = lines.index("event: final")
    final_line = lines[final_index + 1]
    final_payload = json.loads(final_line.removeprefix("data: "))
    assert final_payload["text"]
    assert final_payload["sources"]
    assert final_payload["threadId"]
    assert final_payload["auditId"]
    assert final_payload["guardrailStatus"] == "safe"
    assert final_payload["guardrailReason"] == "ok"
    assert any("SGB" in source.upper() or "CRITÉRIOS DE INCLUSÃO" in source.upper() for source in final_payload["sources"])


@pytest.mark.asyncio
async def test_post_chat_sse_emits_final_for_insufficient_context():
    dummy = _InsufficientGraph(
        final_text="Não encontrei contexto suficiente para responder com segurança.",
        sources=[],
    )
    app = _make_app_with_graph(dummy)
    resolve_patch, append_patch = _persistence_patches()

    with resolve_patch, append_patch:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                "/api/assistant/chat",
                headers={"Accept": "text/event-stream", "X-User-Id": "test-doctor"},
                json={"patientId": "p1", "message": "Quais são os critérios de inclusão para sgb?"},
            )

    assert res.status_code == 200
    text = res.text
    assert "event: final" in text
    lines = text.splitlines()
    final_index = lines.index("event: final")
    final_line = lines[final_index + 1]
    final_payload = json.loads(final_line.removeprefix("data: "))
    assert final_payload["text"]
    assert final_payload["threadId"]
    assert final_payload["auditId"]
    assert final_payload["guardrailStatus"] == "safe"
    assert final_payload["guardrailReason"] == "ok"


def test_chat_payload_does_not_hardcode_retry_or_pipeline_version():
    src_root = Path(__file__).resolve().parents[1] / "src"
    chat_source = (src_root / "assistente_medico_api/api/chat.py").read_text(encoding="utf-8")
    assert '"max_retrieve_attempts": 2' not in chat_source
    legacy_pipeline_version = "separated" + "_nodes_v2"
    assert legacy_pipeline_version not in chat_source
    assert '"generate_grounded_answer"' not in chat_source
    assert '"generate_direct_answer"' not in chat_source
    assert '"generate_insufficient_context"' not in chat_source


def test_prohibited_node_files_are_absent():
    src_root = Path(__file__).resolve().parents[1] / "src"
    base = src_root / "assistente_medico_api/graph/nodes"
    assert not (base / "load_memory.py").exists()
    assert not (base / "save_memory.py").exists()
    assert not (base / "fallback_retrieve.py").exists()
    assert not (base / "pipeline.py").exists()
