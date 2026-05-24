from __future__ import annotations

import asyncio

from langchain_core.documents import Document

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes.generate import (
    generate_direct_answer_node,
    generate_grounded_answer_node,
    generate_insufficient_context_node,
)
from assistente_medico_api.graph.nodes.pipeline import (
    context_quality_router,
    fallback_retrieve_node,
    route_search_needed,
    router_search_needed_node,
)
from assistente_medico_api.graph.nodes.retrieve import retrieve_node
from assistente_medico_api.services import rag_pipeline_service as svc
from assistente_medico_api.services.rag_pipeline_service import (
    run_rerank_and_validate_context,
    run_rewrite_query,
)


def _doc(text: str, **metadata) -> Document:
    return Document(page_content=text, metadata=metadata)


class _FakeStore:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def similarity_search_with_score(self, query: str, k: int = 6, **kwargs):
        self.calls.append({"query": query, "k": k, "kwargs": kwargs})
        if self.responses:
            return self.responses.pop(0)
        return []


def _catalog() -> dict[str, dict]:
    return {
        "sgb": {
            "disease": "Síndrome de Guillain-Barré",
            "diretriz": "Síndrome de Guillain-Barré",
            "disease_normalized": "sindrome de guillain barre",
            "cid10_codes": ["G61.0"],
            "cid10_descriptions": ["Síndrome de Guillain-Barré"],
            "descricao_siglas": ["SGB"],
            "source_stem": "20201022_portaria_conjunta_pcdt_sgb-1",
        }
    }


def test_router_protocol_query_and_smalltalk() -> None:
    clinical = router_search_needed_node({"query": "Quais são os critérios de inclusão para sgb?"})
    greeting = router_search_needed_node({"query": "Olá"})

    assert clinical["search_needed"] is True
    assert route_search_needed(clinical) == "rag"
    assert greeting["search_needed"] is False
    assert route_search_needed(greeting) == "direct"


def test_rewrite_sgb_structured_expansion(monkeypatch) -> None:
    monkeypatch.setattr(svc, "cached_conitec_catalog", lambda: _catalog())

    out = run_rewrite_query("Quais são os critérios de inclusão para sgb?", {}, Settings())

    assert "Síndrome de Guillain-Barré" in out["expanded_query"]
    assert "G61.0" in out["expanded_query"]
    assert "CRITÉRIOS DE INCLUSÃO" in out["expanded_query"]
    assert out["structured_terms"]["disease"] == "Síndrome de Guillain-Barré"
    assert out["structured_terms"]["intent"] == "criterios_inclusao"


def test_retrieve_returns_candidates_not_final_docs(monkeypatch) -> None:
    monkeypatch.setattr(svc, "cached_conitec_catalog", lambda: _catalog())
    rewrite = run_rewrite_query("Quais são os critérios de inclusão para sgb?", {}, Settings())
    store = _FakeStore([(_doc("cid", disease_normalized="sindrome de guillain barre"), 0.1)])

    out = retrieve_node({**rewrite, "query": "Quais são os critérios de inclusão para sgb?"}, store=store, settings=Settings())

    assert len(out["candidate_docs"]) == 1
    assert "retrieved_docs" not in out


def test_rerank_validates_context_and_filters_wrong_disease(monkeypatch) -> None:
    monkeypatch.setattr(svc, "cached_conitec_catalog", lambda: _catalog())
    rewrite = run_rewrite_query("Quais são os critérios de inclusão para sgb?", {}, Settings())
    candidates = [
        _doc("wilson", disease="Doença de Wilson", disease_normalized="doenca de wilson"),
        _doc("inclui", disease="Síndrome de Guillain-Barré", disease_normalized="sindrome de guillain barre", section="CRITÉRIOS DE INCLUSÃO"),
    ]

    out = asyncio.run(
        run_rerank_and_validate_context(
            query="Quais são os critérios de inclusão para sgb?",
            expanded_query=rewrite["expanded_query"],
            structured_terms=rewrite["structured_terms"],
            clinical_understanding=rewrite["clinical_understanding"],
            candidate_docs=candidates,
            settings=Settings(),
        )
    )

    assert out["context_sufficient"] is True
    assert [doc.metadata["disease"] for doc in out["retrieved_docs"]] == ["Síndrome de Guillain-Barré"]


def test_context_quality_router_paths() -> None:
    assert context_quality_router({"context_sufficient": True, "retrieve_attempt": 1, "max_retrieve_attempts": 2}) == "generate_grounded"
    assert context_quality_router({"context_sufficient": False, "retrieve_attempt": 1, "max_retrieve_attempts": 2}) == "fallback_retrieve"
    assert context_quality_router({"context_sufficient": False, "retrieve_attempt": 2, "max_retrieve_attempts": 2}) == "generate_insufficient"


def test_fallback_retrieve_increments_attempt_and_builds_targeted_query(monkeypatch) -> None:
    monkeypatch.setattr(svc, "cached_conitec_catalog", lambda: _catalog())
    state = run_rewrite_query("Quais são os critérios de inclusão para sgb?", {}, Settings())
    state.update({"query": "Quais são os critérios de inclusão para sgb?", "retrieve_attempt": 1})
    store = _FakeStore([(_doc("inclui", disease_normalized="sindrome de guillain barre"), 0.1)])

    out = fallback_retrieve_node(state, store=store, settings=Settings())

    assert out["retrieve_attempt"] == 2
    assert "Síndrome de Guillain-Barré" in store.calls[0]["query"]
    assert "CRITÉRIOS DE INCLUSÃO" in store.calls[0]["query"]


def test_generate_modes(monkeypatch) -> None:
    async def fake_generate(state, settings):
        return {"answer": "Resposta baseada no documento [1].", "rag_audit_payload": {}}

    monkeypatch.setattr("assistente_medico_api.graph.nodes.generate.generate_node", fake_generate)
    grounded = asyncio.run(generate_grounded_answer_node({"retrieved_docs": [_doc("x")]}, Settings()))
    insufficient = asyncio.run(
        generate_insufficient_context_node(
            {"structured_terms": {"disease": "Síndrome de Guillain-Barré"}, "insufficiency_reason": "sem seção"},
            Settings(),
        )
    )
    direct = asyncio.run(generate_direct_answer_node({"query": "Olá", "router_decision": {"search_needed": False}}, Settings()))

    assert "documento" in grounded["answer"]
    assert "Não encontrei trechos suficientes" in insufficient["answer"]
    assert "Olá" in direct["answer"]


def test_after_two_bad_retrieves_generates_insufficient(monkeypatch) -> None:
    monkeypatch.setattr(svc, "cached_conitec_catalog", lambda: _catalog())
    rewrite = run_rewrite_query("Quais são os critérios de inclusão para sgb?", {}, Settings())
    bad_candidates = [_doc("wilson", disease="Doença de Wilson", disease_normalized="doenca de wilson")]

    rerank = asyncio.run(
        run_rerank_and_validate_context(
            query="Quais são os critérios de inclusão para sgb?",
            expanded_query=rewrite["expanded_query"],
            structured_terms=rewrite["structured_terms"],
            clinical_understanding=rewrite["clinical_understanding"],
            candidate_docs=bad_candidates,
            settings=Settings(),
        )
    )
    state = {**rewrite, **rerank, "retrieve_attempt": 2, "max_retrieve_attempts": 2}
    answer = asyncio.run(generate_insufficient_context_node(state, Settings()))

    assert context_quality_router(state) == "generate_insufficient"
    assert "Não encontrei trechos suficientes" in answer["answer"]
