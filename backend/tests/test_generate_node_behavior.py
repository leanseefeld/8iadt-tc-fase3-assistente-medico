import httpx
import pytest

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes import generate as gen_mod
from assistente_medico_api.graph.nodes.generate import _build_messages


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


def test_build_messages_includes_history_and_pcdt_block_in_last_user_turn():
    """Histórico vira Human/Ai; o bloco PCDT fica só na última pergunta."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    state = {
        "query": "segunda pergunta",
        "chat_history": [
            {"role": "user", "content": "primeira"},
            {"role": "assistant", "content": "resposta"},
        ],
        "retrieved_docs": [],
    }
    msgs = _build_messages(state)
    assert len(msgs) == 4
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage) and "primeira" in msgs[1].content
    assert isinstance(msgs[2], AIMessage) and "resposta" in msgs[2].content
    last = msgs[3]
    assert isinstance(last, HumanMessage)
    assert "segunda pergunta" in last.content
    assert "Contexto (trechos PCDT)" in last.content
    assert "(Nenhum trecho recuperado.)" in last.content


@pytest.mark.asyncio
async def test_generate_node_propagates_httpx_timeout(monkeypatch):
    """Timeout do cliente httpx (ReadTimeout) deve propagar sem ser silenciado."""
    monkeypatch.setattr(gen_mod, "_build_llm", lambda _settings: _TimeoutLLM())

    with pytest.raises(httpx.ReadTimeout):
        await gen_mod.generate_node(_STATE, Settings())

