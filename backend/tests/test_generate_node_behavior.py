import httpx
import pytest

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes import generate as gen_mod


class _Chunk:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    async def astream(self, _messages):
        yield _Chunk("parcial-")
        raise RuntimeError("stream broke")


class _TimeoutLLM:
    """Simula httpx.ReadTimeout que o cliente httpx levantaria numa stream travada."""

    async def astream(self, _messages):
        if False:  # pragma: no cover — força async generator
            yield _Chunk("x")
        raise httpx.ReadTimeout("read timed out", request=None)


_STATE = {
    "query": "q",
    "patient_id": "p1",
    "chat_history": [],
    "retrieved_docs": [],
    "sources": [],
    "reasoning_steps": [],
    "answer": "",
}


@pytest.mark.asyncio
async def test_generate_node_propagates_stream_exception(monkeypatch):
    monkeypatch.setattr(gen_mod, "_build_llm", lambda _settings: _FakeLLM())

    with pytest.raises(RuntimeError, match="stream broke"):
        await gen_mod.generate_node(_STATE, Settings())


@pytest.mark.asyncio
async def test_direct_answer_sets_generate_llm_fields(monkeypatch):
    class _StreamLLM:
        async def astream(self, _messages):
            yield _Chunk("resposta-direta")

    monkeypatch.setattr(gen_mod, "_build_llm", lambda _settings: _StreamLLM())
    state = {**_STATE, "generation_mode": "direct_answer"}
    out = await gen_mod.generate_node(state, Settings())
    assert out["generate_llm_output"] == "resposta-direta"
    assert out["generate_llm_input"]
    assert out["generate_llm_input"][-1]["role"] == "user"


@pytest.mark.asyncio
async def test_generate_node_propagates_httpx_timeout(monkeypatch):
    """Timeout do cliente httpx (ReadTimeout) deve propagar sem ser silenciado."""
    monkeypatch.setattr(gen_mod, "_build_llm", lambda _settings: _TimeoutLLM())

    with pytest.raises(httpx.ReadTimeout):
        await gen_mod.generate_node(_STATE, Settings())

