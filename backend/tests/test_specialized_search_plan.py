"""Testes do planejamento de N queries (subgrafo de busca especializada)."""

import pytest
from langchain_core.messages import AIMessage

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.search import nodes as search_nodes
from assistente_medico_api.graph.search.nodes import _parse_queries, plan_queries_node


class _FakeLLM:
    def __init__(self, content: str):
        self._content = content

    async def ainvoke(self, messages):
        return AIMessage(content=self._content)


def test_parse_queries_extracts_and_dedups():
    raw = '{"reasoning":"x","queries":["a","b","a"]}'
    assert _parse_queries(raw, max_n=4, fallback="q") == ["a", "b"]


def test_parse_queries_caps_at_max():
    raw = '{"queries":["a","b","c","d","e"]}'
    assert _parse_queries(raw, max_n=2, fallback="q") == ["a", "b"]


def test_parse_queries_malformed_falls_back():
    assert _parse_queries("not json at all", max_n=4, fallback="pergunta") == ["pergunta"]


def test_parse_queries_handles_surrounding_text():
    raw = 'Claro!\n{"queries":["x","y"]}\nfim'
    assert _parse_queries(raw, max_n=4, fallback="q") == ["x", "y"]


@pytest.mark.asyncio
async def test_plan_queries_node_generates_n(monkeypatch):
    monkeypatch.setattr(
        search_nodes,
        "build_llm",
        lambda settings, **_kw: _FakeLLM('{"reasoning":"r","queries":["q1","q2","q3"]}'),
    )
    out = await plan_queries_node({"query": "tratamento de sepse", "reasoning_steps": []}, Settings())
    # A pergunta original é sempre prepended como 1ª query (1q+Nq).
    assert out["search_queries"] == ["tratamento de sepse", "q1", "q2", "q3"]


@pytest.mark.asyncio
async def test_plan_queries_node_llm_failure_falls_back(monkeypatch):
    def _boom(settings, **_kw):
        raise RuntimeError("modelo indisponível")

    monkeypatch.setattr(search_nodes, "build_llm", _boom)
    out = await plan_queries_node({"query": "tratamento de sepse", "reasoning_steps": []}, Settings())
    assert out["search_queries"] == ["tratamento de sepse"]
    assert out["multi_query_debug"]["error"]


@pytest.mark.asyncio
async def test_plan_queries_node_empty_query():
    out = await plan_queries_node({"query": "   ", "reasoning_steps": []}, Settings())
    assert out["search_queries"] == []
