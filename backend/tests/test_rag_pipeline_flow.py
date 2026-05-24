from __future__ import annotations

import asyncio
import inspect

from langchain_core.documents import Document

from assistente_medico_api.config import Settings
from assistente_medico_api.graph import clinical_entity_resolver
from assistente_medico_api.graph.nodes.generate import (
    generate_direct_answer_node,
    generate_grounded_answer_node,
    generate_insufficient_context_node,
)
from assistente_medico_api.graph.nodes.fallback_retrieve import fallback_retrieve_node
from assistente_medico_api.graph.nodes.load_memory import load_memory_node
from assistente_medico_api.graph.nodes.rerank import context_quality_router
from assistente_medico_api.graph.nodes.retrieve import retrieve_node
from assistente_medico_api.graph.nodes.router import route_search_needed, router_search_needed_node
from assistente_medico_api.graph.nodes.rewrite import rewrite_query_node
from assistente_medico_api.graph.nodes.save_memory import save_memory_node
from assistente_medico_api.services import rag_pipeline_service as svc
from assistente_medico_api.services.rag_pipeline_service import (
    MEMORY_STORE,
    run_full_graph_debug,
    run_load_memory,
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


def test_required_nodes_are_importable_from_nodes_package() -> None:
    import assistente_medico_api.graph.nodes.fallback_retrieve as fallback_retrieve
    import assistente_medico_api.graph.nodes.generate as generate
    import assistente_medico_api.graph.nodes.guardrail as guardrail
    import assistente_medico_api.graph.nodes.load_memory as load_memory
    import assistente_medico_api.graph.nodes.rerank as rerank
    import assistente_medico_api.graph.nodes.retrieve as retrieve
    import assistente_medico_api.graph.nodes.router as router
    import assistente_medico_api.graph.nodes.save_memory as save_memory
    import assistente_medico_api.graph.nodes.rewrite as rewrite

    assert load_memory.load_memory_node
    assert router.router_search_needed_node
    assert rewrite.rewrite_query_node
    assert retrieve.retrieve_attempt_1_node
    assert rerank.rerank_and_validate_context_node
    assert fallback_retrieve.fallback_retrieve_node
    assert generate.generate_grounded_answer_node
    assert guardrail.guardrail_node
    assert save_memory.save_memory_node


def test_memory_uses_structured_terms_without_clinical_hardcode() -> None:
    source = inspect.getsource(run_load_memory)

    assert "Guillain-Barré|Lúpus" not in source
    assert "Insuficiência Adrenal" not in source

    out = load_memory_node(
        {
            "conversation_id": "mem-test",
            "structured_terms": {
                "disease": "Doença Exemplo",
                "disease_normalized": "doenca exemplo",
                "intent": "diagnostico",
            },
        }
    )

    assert out["memory_result"]["last_disease"] == "Doença Exemplo"
    assert out["memory_result"]["last_intent"] == "diagnostico"


def test_follow_up_rewrite_uses_memory_structured_terms(monkeypatch) -> None:
    monkeypatch.setattr(svc, "cached_conitec_catalog", lambda: _catalog())
    memory = {
        "last_structured_terms": {
            "disease": "Síndrome de Guillain-Barré",
            "diretriz": "Síndrome de Guillain-Barré",
            "disease_normalized": "sindrome de guillain barre",
            "cid10_codes": ["G61.0"],
            "intent": "criterios_inclusao",
        }
    }

    out = run_rewrite_query("E os critérios de exclusão?", memory, Settings())

    assert out["rewrite_result"]["resolved_query"] == "E os critérios de exclusão? para Síndrome de Guillain-Barré"
    assert "Síndrome de Guillain-Barré" in out["expanded_query"]
    assert "CRITÉRIOS DE EXCLUSÃO" in out["expanded_query"]


def test_rewrite_node_preserves_main_llm_history_rewrite(monkeypatch) -> None:
    monkeypatch.setattr(svc, "cached_conitec_catalog", lambda: _catalog())
    calls = []

    class _FakeLLM:
        async def ainvoke(self, messages):
            calls.append(messages)

            class _Result:
                content = "Quais são os critérios de exclusão para Síndrome de Guillain-Barré?"

            return _Result()

    monkeypatch.setattr(svc, "_build_llm", lambda settings: _FakeLLM())
    state = {
        "query": "E os critérios de exclusão?",
        "memory_result": {
            "history_transcript": "Usuário: Quais são os critérios de inclusão para SGB?\nAssistente: Síndrome de Guillain-Barré...",
            "last_structured_terms": {
                "disease": "Síndrome de Guillain-Barré",
                "diretriz": "Síndrome de Guillain-Barré",
                "disease_normalized": "sindrome de guillain barre",
                "cid10_codes": ["G61.0"],
            },
        },
    }

    out = asyncio.run(rewrite_query_node(state, Settings()))

    assert calls
    assert out["rewrite_result"]["llm_rewrite_used"] is True
    assert out["rewrite_result"]["resolved_query"] == "Quais são os critérios de exclusão para Síndrome de Guillain-Barré?"
    assert "CRITÉRIOS DE EXCLUSÃO" in out["expanded_query"]


def test_clinical_entity_resolver_uses_medspacy_when_available(monkeypatch) -> None:
    class _Ent:
        text = "diabetes"
        label_ = "PROBLEM"

    class _Doc:
        ents = [_Ent()]

    class _NLP:
        def __call__(self, text):
            return _Doc()

    monkeypatch.setattr(clinical_entity_resolver, "_load_spacy_pipeline", lambda: (_NLP(), "medspacy"))

    out = clinical_entity_resolver.resolve_clinical_entities("diabetes", catalog={})

    assert out["medspacy_used"] is True
    assert out["spacy_used"] is True
    assert out["linked_entities"][0]["source"] == "medspacy"


def test_clinical_entity_resolver_fallback_does_not_break(monkeypatch) -> None:
    monkeypatch.setattr(clinical_entity_resolver, "_load_spacy_pipeline", lambda: (None, "none"))

    out = clinical_entity_resolver.resolve_clinical_entities("pergunta sem backend", catalog={})

    assert out["medspacy_used"] is False
    assert out["linked_entities"] == []


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
    assert out["retrieve_result"]["candidate_count"] == 1
    assert out["retrieve_result"]["fallback_to_unfiltered"] is False


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
    assert out["rerank_result"]["context_quality"] == "sufficient"
    assert [doc.metadata["disease"] for doc in out["retrieved_docs"]] == ["Síndrome de Guillain-Barré"]


def test_rerank_missing_preferred_section_is_partial_and_triggers_fallback(monkeypatch) -> None:
    monkeypatch.setattr(svc, "cached_conitec_catalog", lambda: _catalog())
    rewrite = run_rewrite_query("Quais são os critérios de inclusão para sgb?", {}, Settings())
    candidates = [
        _doc(
            "cid",
            disease="Síndrome de Guillain-Barré",
            disease_normalized="sindrome de guillain barre",
            section="CID-10",
        )
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
    state = {**rewrite, **out, "retrieve_attempt": 1, "max_retrieve_attempts": 2}

    assert out["context_sufficient"] is False
    assert out["rerank_result"]["context_quality"] == "partial"
    assert out["rerank_result"]["failure_type"] == "missing_preferred_section"
    assert context_quality_router(state) == "fallback_retrieve"


def test_context_quality_router_paths() -> None:
    assert context_quality_router({"rerank_result": {"context_quality": "sufficient"}, "retrieve_attempt": 1, "max_retrieve_attempts": 2}) == "generate_grounded"
    assert context_quality_router({"rerank_result": {"context_quality": "partial"}, "retrieve_attempt": 1, "max_retrieve_attempts": 2}) == "fallback_retrieve"
    assert context_quality_router({"rerank_result": {"context_quality": "insufficient"}, "retrieve_attempt": 2, "max_retrieve_attempts": 2}) == "generate_insufficient"


def test_fallback_retrieve_increments_attempt_and_builds_targeted_query(monkeypatch) -> None:
    monkeypatch.setattr(svc, "cached_conitec_catalog", lambda: _catalog())
    state = run_rewrite_query("Quais são os critérios de inclusão para sgb?", {}, Settings())
    state.update({"query": "Quais são os critérios de inclusão para sgb?", "retrieve_attempt": 1})
    store = _FakeStore([(_doc("inclui", disease_normalized="sindrome de guillain barre"), 0.1)])

    out = fallback_retrieve_node(state, store=store, settings=Settings())

    assert out["retrieve_attempt"] == 2
    assert "Síndrome de Guillain-Barré" in store.calls[0]["query"]
    assert "CRITÉRIOS DE INCLUSÃO" in store.calls[0]["query"]
    assert "candidate_docs_attempt_2" in out


def test_generate_modes(monkeypatch) -> None:
    async def fake_generate(state, settings):
        return {"answer": "Resposta baseada no documento [1].", "rag_audit_payload": {}}

    monkeypatch.setattr("assistente_medico_api.graph.nodes.generate.generate_node", fake_generate)
    grounded = asyncio.run(
        generate_grounded_answer_node(
            {"retrieved_docs": [_doc("x")], "rerank_result": {"context_quality": "sufficient"}},
            Settings(),
        )
    )
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


def test_save_memory_persists_structured_update(monkeypatch) -> None:
    MEMORY_STORE._data.clear()
    state = {
        "conversation_id": "conv-save",
        "query": "Quais são os critérios de inclusão para sgb?",
        "answer": "Resposta final segura.",
        "structured_terms": {"disease": "Síndrome de Guillain-Barré", "intent": "criterios_inclusao"},
        "sources": ["[1] PCDT Síndrome de Guillain-Barré"],
        "rerank_result": {"context_quality": "sufficient"},
        "audit_id": "audit-1",
    }

    out = save_memory_node(state, settings=Settings())
    loaded = MEMORY_STORE.load("conv-save")

    assert out["memory_saved"] is True
    assert loaded["last_structured_terms"]["disease"] == "Síndrome de Guillain-Barré"
    assert loaded["last_sources"] == ["[1] PCDT Síndrome de Guillain-Barré"]


def test_inspector_debug_pipeline_matches_backend_rewrite(monkeypatch) -> None:
    monkeypatch.setattr(svc, "cached_conitec_catalog", lambda: _catalog())
    settings = Settings()
    first = [
        (
            _doc(
                "serão incluídos pacientes",
                disease="Síndrome de Guillain-Barré",
                diretriz="Síndrome de Guillain-Barré",
                disease_normalized="sindrome de guillain barre",
                section="CRITÉRIOS DE INCLUSÃO",
                cid10_codes=["G61.0"],
            ),
            0.1,
        )
    ]
    store = _FakeStore(first)
    query = "Quais são os critérios de inclusão para sgb?"

    graph_debug = asyncio.run(run_full_graph_debug(query=query, settings=settings, store=store, conversation_id="debug-test"))
    rewrite = run_rewrite_query(query, {}, settings)

    state = graph_debug["state"]
    assert state["expanded_query"] == rewrite["expanded_query"]
    assert state["structured_terms"] == rewrite["structured_terms"]
    assert state["rerank_result"]["context_quality"] == "sufficient"
