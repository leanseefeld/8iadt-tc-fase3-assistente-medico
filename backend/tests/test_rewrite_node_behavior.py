import pytest

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes import rewrite as rw_mod
from assistente_medico_api.graph.nodes.rewrite import rewrite_query_node
from assistente_medico_api.services.rag_query_expansion_service import (
    QueryExpansionResult,
    RetrievalQueryResolution,
)


def _expansion() -> QueryExpansionResult:
    return QueryExpansionResult(
        expanded_query="consulta expandida",
        clinical_understanding={"intent": "criterios_inclusao"},
        structured_terms={"intent": "criterios_inclusao", "cid10_codes": ["G61.0"]},
        query_expansion={"expanded_query": "consulta expandida"},
    )


@pytest.mark.asyncio
async def test_rewrite_without_query_returns_empty_retrieval_query(monkeypatch):
    monkeypatch.setattr(rw_mod, "expand_query_for_retrieval", lambda **_kwargs: _expansion())

    out = await rewrite_query_node({"query": "  ", "chat_history": [], "reasoning_steps": []}, Settings())

    assert out["retrieval_query"] == ""
    assert any("pergunta vazia" in step.lower() for step in out["reasoning_steps"])


@pytest.mark.asyncio
async def test_rewrite_without_history_uses_literal_query(monkeypatch):
    monkeypatch.setattr(rw_mod, "expand_query_for_retrieval", lambda **_kwargs: _expansion())

    out = await rewrite_query_node(
        {
            "query": "Quais são os critérios de inclusão para sgb?",
            "chat_history": [],
            "reasoning_steps": [],
        },
        Settings(),
    )

    assert out["retrieval_query"] == "Quais são os critérios de inclusão para sgb?"
    assert out["expanded_query"] == "consulta expandida"
    assert out["structured_terms"]["cid10_codes"] == ["G61.0"]
    assert any("sem histórico" in step.lower() for step in out["reasoning_steps"])


@pytest.mark.asyncio
async def test_rewrite_with_history_uses_llm_output(monkeypatch):
    async def _resolve(*, state, query, settings, trace=None):
        _ = (state, query, settings, trace)
        return RetrievalQueryResolution(
            retrieval_query="consulta reescrita autocontida",
            reasoning_steps=["Busca: pergunta reescrita com o histórico para recuperação."],
            used_history=True,
            llm_used=True,
        )

    monkeypatch.setattr(rw_mod, "resolve_retrieval_query", _resolve)
    monkeypatch.setattr(rw_mod, "expand_query_for_retrieval", lambda **_kwargs: _expansion())

    out = await rewrite_query_node(
        {
            "query": "e as contraindicações?",
            "chat_history": [
                {"role": "user", "content": "Tratamento de HAS no idoso?"},
                {"role": "assistant", "content": "Ver PCDT de hipertensão..."},
            ],
            "reasoning_steps": [],
        },
        Settings(),
    )

    assert out["retrieval_query"] == "consulta reescrita autocontida"
    assert out["expanded_query"] == "consulta expandida"
    assert any("reescrita" in step.lower() for step in out["reasoning_steps"])
