import pytest

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes import rewrite as rw_mod
from assistente_medico_api.graph.nodes.rewrite import rewrite_query_node


@pytest.mark.asyncio
async def test_rewrite_without_history_uses_literal_query():
    state = {
        "query": "  diabetes tipo 2  ",
        "chat_history": [],
        "reasoning_steps": [],
    }
    out = await rewrite_query_node(state, Settings())
    assert out["retrieval_query"] == "diabetes tipo 2"
    assert any("sem histórico" in s for s in out["reasoning_steps"])


@pytest.mark.asyncio
async def test_rewrite_with_history_calls_llm(monkeypatch):
    class _Msg:
        content = "consulta reescrita autocontida"

    class _LLM:
        async def ainvoke(self, _messages):
            return _Msg()

    monkeypatch.setattr(rw_mod, "_build_llm", lambda _s: _LLM())

    state = {
        "query": "e as contraindicações?",
        "chat_history": [
            {"role": "user", "content": "Tratamento de HAS no idoso?"},
            {"role": "assistant", "content": "Ver PCDT de hipertensão..."},
        ],
        "reasoning_steps": [],
    }
    out = await rewrite_query_node(state, Settings())
    assert out["retrieval_query"] == "consulta reescrita autocontida"
    assert any("reescrita" in s.lower() for s in out["reasoning_steps"])


@pytest.mark.asyncio
async def test_rewrite_on_llm_failure_falls_back(monkeypatch):
    class _LLM:
        async def ainvoke(self, _messages):
            raise RuntimeError("ollama off")

    monkeypatch.setattr(rw_mod, "_build_llm", lambda _s: _LLM())

    state = {
        "query": "pergunta",
        "chat_history": [{"role": "user", "content": "antes"}],
        "reasoning_steps": [],
    }
    out = await rewrite_query_node(state, Settings())
    assert out["retrieval_query"] == "pergunta"
    assert any("falha na reescrita" in s for s in out["reasoning_steps"])
