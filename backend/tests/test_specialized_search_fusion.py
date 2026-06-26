"""Testes da fusão RRF e do nó de busca (subgrafo de busca especializada)."""

from langchain_core.documents import Document

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.search.nodes import _rrf_fuse, search_node


def _doc(doc_id: str, stem: str = "s", **meta) -> Document:
    return Document(page_content=f"conteudo {doc_id}", metadata={"source_stem": stem, **meta}, id=doc_id)


def test_rrf_fuse_dedups_and_ranks_shared_docs_first():
    d1, d2, d3 = _doc("1"), _doc("2"), _doc("3")
    # Query A: d1, d2 ; Query B: d2, d3 — d2 aparece nas duas → maior RRF.
    results = [[(d1, 0.9), (d2, 0.8)], [(d2, 0.7), (d3, 0.6)]]
    fused = _rrf_fuse(results, rrf_k=60, top_k=10)
    keys = [d.id for d in fused]
    assert keys[0] == "2"
    assert set(keys) == {"1", "2", "3"}
    assert fused[0].metadata["matched_queries"] == 2
    assert "rrf_score" in fused[0].metadata


def test_rrf_fuse_respects_top_k():
    results = [[(_doc(str(i)), 1.0) for i in range(5)]]
    fused = _rrf_fuse(results, rrf_k=60, top_k=2)
    assert len(fused) == 2


class _FakeStore:
    def __init__(self, mapping):
        self._mapping = mapping

    def similarity_search_with_score(self, query, k):
        return self._mapping.get(query, [])[:k]


def test_search_node_fuses_and_sets_sources():
    d1 = _doc("1", diretriz="Sepse", section="Tratamento", page_start=1, page_end=2)
    d2 = _doc("2", diretriz="Sepse", section="Diagnóstico", page_start=3, page_end=4)
    store = _FakeStore({"q1": [(d1, 0.9)], "q2": [(d2, 0.8), (d1, 0.5)]})
    out = search_node({"search_queries": ["q1", "q2"], "reasoning_steps": []}, store=store, settings=Settings())
    assert out["generation_mode"] == "grounded_answer"
    assert out["context_sufficient"] is True
    assert len(out["retrieved_docs"]) == 2
    assert out["sources"][0].startswith("[1] PCDT")


def test_search_node_without_results_is_insufficient():
    out = search_node({"search_queries": ["q1"], "reasoning_steps": []}, store=_FakeStore({}), settings=Settings())
    assert out["generation_mode"] == "insufficient_context"
    assert out["retrieved_docs"] == []
    assert out["context_sufficient"] is False


def test_search_node_falls_back_to_query_when_no_planned_queries():
    d1 = _doc("1", diretriz="Sepse")
    store = _FakeStore({"pergunta literal": [(d1, 0.9)]})
    out = search_node({"query": "pergunta literal", "reasoning_steps": []}, store=store, settings=Settings())
    assert len(out["retrieved_docs"]) == 1
