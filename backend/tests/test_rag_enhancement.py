from __future__ import annotations

import json
import asyncio
import inspect
from pathlib import Path

from langchain_core.documents import Document

from assistente_medico_api.config import Settings
from assistente_medico_api.graph import cross_encoder_reranker as ce_mod
from assistente_medico_api.graph.nodes.generate import _build_messages, generate_node
from assistente_medico_api.graph.nodes.retrieve import retrieve_node
from assistente_medico_api.services import rag_pipeline_service as rag_service
from assistente_medico_api.services.rag_pipeline_service import (
    run_rerank_and_validate_context,
    run_rewrite_query,
)
from assistente_medico_api.graph.clinical_query_understanding import (
    understand_clinical_query,
)
from assistente_medico_api.graph.cross_encoder_reranker import apply_cross_encoder_rerank
from assistente_medico_api.graph.rag_enhancement import (
    append_audit_jsonl,
    expand_query_with_conitec_catalog,
    extract_query_entities,
    filter_documents_by_detected_disease,
    format_context_document,
    rerank_documents,
)


def _assert_clean_expanded_query(expanded_query: str) -> None:
    assert "cid10_codes:" not in expanded_query
    assert "structured_terms:" not in expanded_query
    assert "{" not in expanded_query
    assert "}" not in expanded_query
    assert "[" not in expanded_query
    assert "]" not in expanded_query
    assert '"' not in expanded_query


def _catalog() -> dict[str, dict]:
    return {
        "insuficiencia adrenal": {
            "disease": "Insuficiência Adrenal",
            "diretriz": "Insuficiência Adrenal",
            "cid10_codes": ["E23.0", "E23.3", "E27.1", "E27.2", "E27.3", "E27.4"],
            "cid10_descriptions": ["Insuficiência adrenocortical primária"],
            "medicamentos": [
                "Hidrocortisona comprimido 10 mg",
                "Acetato de fludrocortisona comprimido 0,1 mg",
                "Prednisona comprimido 20 mg",
            ],
            "descricao_siglas": ["PCDT"],
        },
        "lipofuscinose ceroide neuronal tipo 2": {
            "disease": "Lipofuscinose Ceroide Neuronal tipo 2",
            "diretriz": "Lipofuscinose Ceroide Neuronal tipo 2",
            "cid10_codes": ["E75.4"],
            "cid10_descriptions": ["Lipofuscinose neuronal ceroide"],
            "medicamentos": ["Alfacerliponase solução injetável 30 mg/mL"],
            "descricao_siglas": [],
        },
        "artrite reumatoide": {
            "disease": "Artrite Reumatoide",
            "diretriz": "Artrite Reumatoide",
            "cid10_codes": ["M05", "M05.0", "M06"],
            "cid10_descriptions": ["Artrite reumatoide soropositiva", "Outras artrites reumatoides"],
            "medicamentos": ["Metotrexato", "Leflunomida"],
            "descricao_siglas": ["AR"],
        },
        "artrite idiopatica juvenil": {
            "disease": "Artrite Idiopática Juvenil",
            "diretriz": "Artrite Idiopática Juvenil",
            "cid10_codes": ["M08"],
            "cid10_descriptions": ["Artrite juvenil"],
            "medicamentos": ["Adalimumabe"],
            "descricao_siglas": ["AIJ"],
        },
        "asma": {
            "disease": "Asma",
            "diretriz": "Asma",
            "cid10_codes": ["J45"],
            "cid10_descriptions": ["Asma"],
            "medicamentos": ["Budesonida"],
            "descricao_siglas": [],
        },
        "mucopolissacaridose": {
            "disease": "Mucopolissacaridose",
            "diretriz": "Mucopolissacaridose",
            "cid10_codes": ["E76"],
            "cid10_descriptions": ["Distúrbios do metabolismo do glicosaminoglicano"],
            "medicamentos": ["Laronidase"],
            "descricao_siglas": [],
        },
        "hiv criancas adolescentes": {
            "disease": "Infecção pelo HIV em Crianças e Adolescentes",
            "diretriz": (
                "Manejo da Infecção pelo HIV em Crianças e Adolescentes - Módulo 2 - "
                "Diagnóstico, Manejo e Tratamento de Crianças e Adolescentes Vivendo com HIV"
            ),
            "disease_normalized": "infeccao pelo hiv em criancas e adolescentes",
            "cid10_codes": ["B20", "B24"],
            "cid10_descriptions": ["Doença pelo vírus da imunodeficiência humana"],
            "medicamentos": ["Dolutegravir", "Lamivudina"],
            "descricao_siglas": ["HIV"],
            "source_stem": "pcdt_hiv_criancas_adolescentes_modulo_2",
        },
        "hiv adultos": {
            "disease": "Infecção pelo HIV em Adultos",
            "diretriz": "Manejo da Infecção pelo HIV em Adultos - Módulo 1 - Tratamento",
            "disease_normalized": "infeccao pelo hiv em adultos",
            "cid10_codes": ["B20", "B24"],
            "cid10_descriptions": ["Doença pelo vírus da imunodeficiência humana"],
            "medicamentos": ["Dolutegravir", "Lamivudina"],
            "descricao_siglas": ["HIV"],
            "source_stem": "pcdt_hiv_adultos_modulo_1",
        },
        "sindrome guillain barre": {
            "disease": "Síndrome de Guillain-Barré",
            "diretriz": "Síndrome de Guillain-Barré",
            "disease_normalized": "sindrome de guillain barre",
            "cid10_codes": ["G61.0"],
            "cid10_descriptions": ["Síndrome de Guillain-Barré"],
            "medicamentos": ["Imunoglobulina humana"],
            "descricao_siglas": ["SGB"],
            "source_stem": "20201022_portaria_conjunta_pcdt_sgb-1",
        },
        "lupus eritematoso sistemico": {
            "disease": "Lúpus Eritematoso Sistêmico",
            "diretriz": "Lúpus Eritematoso Sistêmico",
            "disease_normalized": "lupus eritematoso sistemico",
            "cid10_codes": ["M32"],
            "cid10_descriptions": ["Lúpus eritematoso sistêmico"],
            "medicamentos": ["Hidroxicloroquina"],
            "descricao_siglas": ["LES"],
            "source_stem": "20221109_pcdt_lupus",
        },
    }


def _doc(text: str, **metadata) -> Document:
    return Document(page_content=text, metadata=metadata)


class _FakeStore:
    def __init__(self, *responses: list[tuple[Document, float]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def similarity_search_with_score(self, query: str, k: int = 6, **kwargs):
        self.calls.append({"query": query, "k": k, "kwargs": kwargs})
        if self.responses:
            return self.responses.pop(0)
        return []


def test_medical_chat_pipeline_expands_hiv_pediatric_query_and_filters_wrong_docs() -> None:
    expanded = expand_query_with_conitec_catalog("Como tratar HIV em crianças?", _catalog())
    docs = [
        (
            _doc(
                "tratamento pediátrico",
                disease="Infecção pelo HIV em Crianças e Adolescentes",
                diretriz="Manejo da Infecção pelo HIV em Crianças e Adolescentes - Módulo 2 - Diagnóstico, Manejo e Tratamento de Crianças e Adolescentes Vivendo com HIV",
                section="TRATAMENTO",
            ),
            0.2,
        ),
        (_doc("texto AIJ", disease="Artrite Idiopática Juvenil", diretriz="Artrite Idiopática Juvenil", section="TRATAMENTO"), 0.9),
        (_doc("texto MPS", disease="Mucopolissacaridose", diretriz="Mucopolissacaridose", section="TRATAMENTO"), 0.8),
    ]

    ranked = rerank_documents("Como tratar HIV em crianças?", expanded, docs, final_k=5)

    assert expanded["clinical_understanding"]["intent"] == "tratamento"
    assert expanded["catalog_candidates"][0]["disease"] == "Infecção pelo HIV em Crianças e Adolescentes"
    assert "Manejo da Infecção pelo HIV em Crianças e Adolescentes" in expanded["expanded_query"]
    assert [doc.metadata["disease"] for doc in ranked] == ["Infecção pelo HIV em Crianças e Adolescentes"]


def test_medical_chat_pipeline_resolves_sgb_for_inclusion_criteria() -> None:
    expanded = expand_query_with_conitec_catalog("Quais são os critérios de inclusão para sgb?", _catalog())

    assert expanded["clinical_understanding"]["intent"] == "criterios_inclusao"
    assert expanded["catalog_candidates"][0]["disease"] == "Síndrome de Guillain-Barré"
    assert "Síndrome de Guillain-Barré" in expanded["expanded_query"]
    assert "G61.0" in expanded["expanded_query"]
    assert "CRITÉRIOS DE INCLUSÃO" in expanded["expanded_query"]
    _assert_clean_expanded_query(expanded["expanded_query"])
    assert expanded["structured_terms"]["cid10_codes"] == ["G61.0"]
    assert expanded["structured_terms"]["intent"] == "criterios_inclusao"


def test_medical_chat_pipeline_resolves_lupus_and_diagnostic_intent() -> None:
    expanded = expand_query_with_conitec_catalog("Como eu reconheço uma criança com lupus?", _catalog())

    assert expanded["clinical_understanding"]["intent"] == "diagnostico"
    assert expanded["catalog_candidates"][0]["disease"] == "Lúpus Eritematoso Sistêmico"
    assert "Lúpus Eritematoso Sistêmico" in expanded["expanded_query"]
    assert "M32" in expanded["expanded_query"]
    assert "DIAGNÓSTICO" in expanded["expanded_query"]
    _assert_clean_expanded_query(expanded["expanded_query"])
    assert "M32" in expanded["structured_terms"]["cid10_codes"]
    assert expanded["structured_terms"]["intent"] == "diagnostico"


def test_lupus_diagnostic_query_filters_other_diagnostic_documents() -> None:
    expanded = expand_query_with_conitec_catalog("Como reconhecer uma criança com lupus?", _catalog())
    docs = [
        (_doc("diagnóstico Wilson", disease="Doença de Wilson", diretriz="Doença de Wilson", section="DIAGNÓSTICO"), 0.1),
        (_doc("diagnóstico brucelose", disease="Brucelose", diretriz="Brucelose", section="DIAGNÓSTICO"), 0.2),
        (_doc("diagnóstico lupus", disease="Lúpus Eritematoso Sistêmico", diretriz="Lúpus Eritematoso Sistêmico", section="DIAGNÓSTICO", cid10_codes=["M32"]), 0.3),
    ]

    ranked = rerank_documents("Como reconhecer uma criança com lupus?", expanded, docs, final_k=6)

    assert "Lúpus Eritematoso Sistêmico" in expanded["expanded_query"]
    assert [doc.metadata["disease"] for doc in ranked] == ["Lúpus Eritematoso Sistêmico"]


def test_no_catalog_candidate_marks_low_confidence_and_keeps_section_match_weak() -> None:
    expanded = expand_query_with_conitec_catalog("Como reconhecer uma criança?", _catalog())
    docs = [
        (_doc("diagnóstico Wilson", disease="Doença de Wilson", diretriz="Doença de Wilson", section="DIAGNÓSTICO"), 0.1),
        (_doc("diagnóstico brucelose", disease="Brucelose", diretriz="Brucelose", section="DIAGNÓSTICO"), 0.2),
    ]

    ranked = rerank_documents("Como reconhecer uma criança?", expanded, docs, final_k=2)
    assert expanded["structured_terms"]["catalog_candidates"] == []
    assert all(
        not reason.startswith("section_intent_match:")
        for doc in ranked
        for reason in doc.metadata["ranking_reasons"]
    )
    assert any(
        reason.startswith("section_intent_match_weak:")
        for doc in ranked
        for reason in doc.metadata["ranking_reasons"]
    )


def test_understand_clinical_query_fallback_without_catalog() -> None:
    understanding = understand_clinical_query("O que o PCDT diz sobre E27.1?", None)

    assert understanding["original_query"] == "O que o PCDT diz sobre E27.1?"
    assert understanding["detected_cid10_codes"] == ["E27.1"]
    assert understanding["detected_disease"] is None


def test_catalog_fallback_works_without_linked_biomedical_entities() -> None:
    understanding = understand_clinical_query("Quais são os critérios de inclusão para sgb?", _catalog())

    assert "linked_entities" not in understanding
    assert understanding["detected_disease"]["name"] == "Síndrome de Guillain-Barré"
    assert understanding["catalog_candidates"][0]["source"] == "catalog_semantic"


def test_extract_query_entities_detects_cid_and_intent() -> None:
    entities = extract_query_entities("Quais critérios de inclusão para E27.1?", _catalog())

    assert entities["cid10_codes"] == ["E27.1"]
    assert entities["section_intent"] == "criterios_inclusao"


def test_extract_query_entities_detects_treatment_and_empty_query() -> None:
    assert extract_query_entities("tratamento com hidrocortisona", _catalog())["section_intent"] == "tratamento"
    empty = extract_query_entities("", _catalog())
    assert empty["cid10_codes"] == []
    assert empty["section_intent"] is None


def test_expand_query_with_conitec_catalog_expands_disease_without_cid_or_medication_for_inclusion() -> None:
    expanded = expand_query_with_conitec_catalog("critérios para insuficiência adrenal", _catalog(), max_terms=10)

    assert expanded["structured_terms"]["disease"] == "Insuficiência Adrenal"
    assert "E27.1" in expanded["structured_terms"]["cid10_codes"]
    assert expanded["structured_terms"]["medications"] == []
    assert "E23.0" not in expanded["expanded_query"]


def test_expand_query_with_conitec_catalog_includes_medications_for_treatment_intent() -> None:
    expanded = expand_query_with_conitec_catalog("tratamento para insuficiência adrenal", _catalog(), max_terms=10)

    assert expanded["structured_terms"]["disease"] == "Insuficiência Adrenal"
    assert any("Prednisona" in med for med in expanded["structured_terms"]["medications"])


def test_expand_query_with_conitec_catalog_expands_cid_to_diretriz() -> None:
    expanded = expand_query_with_conitec_catalog("Paciente com E75.4", _catalog(), max_terms=8)

    assert expanded["structured_terms"]["disease"] == "Lipofuscinose Ceroide Neuronal tipo 2"
    assert "Lipofuscinose Ceroide Neuronal tipo 2" in expanded["expanded_query"]


def test_expand_query_with_conitec_catalog_fallback_and_max_terms() -> None:
    expanded = expand_query_with_conitec_catalog("doença desconhecida", _catalog(), max_terms=2)

    assert expanded["expanded_query"] == "doença desconhecida"
    assert "matched_terms" not in expanded

    expanded_known = expand_query_with_conitec_catalog("insuficiência adrenal", _catalog(), max_terms=2)
    assert expanded_known["expanded_query"].startswith("insuficiência adrenal")


def test_expand_query_with_conitec_catalog_is_restrictive_for_rheumatoid_arthritis() -> None:
    expanded = expand_query_with_conitec_catalog(
        "Quais são os critérios de inclusão para artrite reumatoide?",
        _catalog(),
        max_terms=20,
    )

    assert expanded["structured_terms"]["disease"] == "Artrite Reumatoide"
    assert expanded["structured_terms"]["medications"] == []
    assert expanded["structured_terms"]["intent"] == "criterios_inclusao"
    assert "Artrite Reumatoide" in expanded["expanded_query"]
    assert "CRITÉRIOS DE INCLUSÃO" in expanded["expanded_query"]
    _assert_clean_expanded_query(expanded["expanded_query"])
    assert "M05" not in expanded["expanded_query"]
    assert "M06" not in expanded["expanded_query"]
    assert "Metotrexato" not in expanded["expanded_query"]
    assert "Artrite Idiopática Juvenil" not in expanded["expanded_query"]
    assert "Asma" not in expanded["expanded_query"]


def test_rerank_documents_boosts_exact_cid_and_preserves_scores() -> None:
    expansion = expand_query_with_conitec_catalog("Paciente com E27.1", _catalog())
    docs = [
        (_doc("texto geral", source_stem="x", cid10_codes=["A00"], section="INTRODUÇÃO"), 0.1),
        (_doc("texto E27.1", source_stem="ia", cid10_codes=["E27.1"], section="DIAGNÓSTICO"), 0.9),
    ]

    ranked = rerank_documents("Paciente com E27.1", expansion, docs, final_k=2)

    assert ranked[0].metadata["source_stem"] == "ia"
    assert ranked[0].metadata["dense_score"] == 0.9
    assert any(reason == "cid_explicit_match:E27.1" for reason in ranked[0].metadata["ranking_reasons"])


def test_rerank_documents_boosts_section_and_penalizes_admin() -> None:
    expansion = expand_query_with_conitec_catalog("critérios de inclusão para insuficiência adrenal", _catalog())
    docs = [
        (_doc("texto administrativo", disease="Insuficiência Adrenal", section="REGULAÇÃO/CONTROLE/AVALIAÇÃO PELO GESTOR"), 0.1),
        (_doc("serão incluídos", disease="Insuficiência Adrenal", section="CRITÉRIOS DE INCLUSÃO"), 0.2),
    ]

    ranked = rerank_documents("critérios de inclusão para insuficiência adrenal", expansion, docs, final_k=2)

    assert ranked[0].metadata["section"] == "CRITÉRIOS DE INCLUSÃO"
    assert any("section_intent_match:criterios_inclusao" == reason for reason in ranked[0].metadata["ranking_reasons"])
    assert any(reason.startswith("penalty_wrong_section:") for reason in ranked[1].metadata["ranking_reasons"])


def test_rerank_documents_does_not_match_rheumatoid_arthritis_to_juvenile_arthritis() -> None:
    expansion = expand_query_with_conitec_catalog(
        "Quais são os critérios de inclusão para artrite reumatoide?",
        _catalog(),
    )
    docs = [
        (
            _doc(
                "texto",
                disease="Artrite Idiopática Juvenil",
                diretriz="Artrite Idiopática Juvenil",
                section="CRITÉRIOS DE INCLUSÃO",
            ),
            0.1,
        ),
        (
            _doc(
                "texto",
                disease="Artrite Reumatoide",
                diretriz="Artrite Reumatoide",
                section="CID-10",
            ),
            0.2,
        ),
    ]

    ranked = rerank_documents("Quais são os critérios de inclusão para artrite reumatoide?", expansion, docs, final_k=2)

    assert len(ranked) == 1
    assert ranked[0].metadata["disease"] == "Artrite Reumatoide"
    assert all("Artrite Idiopática Juvenil" != doc.metadata["disease"] for doc in ranked)


def test_rerank_documents_does_not_complete_sgb_with_wrong_diseases() -> None:
    expansion = expand_query_with_conitec_catalog("Quais são os critérios de inclusão para sgb?", _catalog())
    docs = [
        (_doc("G61.0", disease="Síndrome de Guillain-Barré", diretriz="Síndrome de Guillain-Barré", section="CID-10", cid10_codes=["G61.0"]), 0.1),
        (_doc("paget", disease="Doença de Paget", diretriz="Doença de Paget", section="CID-10"), 0.2),
        (_doc("mps", disease="Mucopolissacaridose", diretriz="Mucopolissacaridose", section="CRITÉRIOS DE EXCLUSÃO"), 0.3),
        (_doc("gaucher", disease="Doença de Gaucher", diretriz="Doença de Gaucher", section="MEDICAMENTOS"), 0.4),
    ]

    ranked = rerank_documents("Quais são os critérios de inclusão para sgb?", expansion, docs, final_k=6)

    assert [doc.metadata["disease"] for doc in ranked] == ["Síndrome de Guillain-Barré"]
    assert expansion["_catalog_filter_info"]["candidate_count_after_filter"] == 1
    assert expansion["_catalog_filter_info"]["final_documents_count"] == 1


def test_rerank_documents_prefers_sgb_inclusion_section_over_cid10() -> None:
    expansion = expand_query_with_conitec_catalog("Quais são os critérios de inclusão para sgb?", _catalog())
    docs = [
        (_doc("G61.0", disease="Síndrome de Guillain-Barré", diretriz="Síndrome de Guillain-Barré", section="CID-10", cid10_codes=["G61.0"]), 0.1),
        (_doc("serão incluídos pacientes", disease="Síndrome de Guillain-Barré", diretriz="Síndrome de Guillain-Barré", section="CRITÉRIOS DE INCLUSÃO", cid10_codes=["G61.0"]), 0.2),
    ]

    ranked = rerank_documents("Quais são os critérios de inclusão para sgb?", expansion, docs, final_k=2)

    assert [doc.metadata["section"] for doc in ranked] == ["CRITÉRIOS DE INCLUSÃO", "CID-10"]
    assert "section_intent_match:criterios_inclusao" in ranked[0].metadata["ranking_reasons"]
    assert any(reason.startswith("cid_catalog_hint_ignored:") for reason in ranked[1].metadata["ranking_reasons"])


def test_retrieve_node_runs_complementary_search_for_sgb_missing_preferred_section(monkeypatch) -> None:
    monkeypatch.setattr(rag_service, "cached_conitec_catalog", lambda: _catalog())
    first = [
        (
            _doc(
                "G61.0",
                disease="Síndrome de Guillain-Barré",
                diretriz="Síndrome de Guillain-Barré",
                disease_normalized="sindrome de guillain barre",
                section="CID-10",
                cid10_codes=["G61.0"],
            ),
            0.1,
        )
    ]
    second = [
        (
            _doc(
                "serão incluídos pacientes",
                disease="Síndrome de Guillain-Barré",
                diretriz="Síndrome de Guillain-Barré",
                disease_normalized="sindrome de guillain barre",
                section="CRITÉRIOS DE INCLUSÃO",
                cid10_codes=["G61.0"],
            ),
            0.2,
        )
    ]
    store = _FakeStore(first, second)
    settings = Settings(rag_retrieve_candidates_k=10, rag_retrieve_final_k=6)

    rewrite = run_rewrite_query("Quais são os critérios de inclusão para sgb?", {}, settings)
    out = retrieve_node({**rewrite, "query": "Quais são os critérios de inclusão para sgb?"}, store=store, settings=settings)
    assert "candidate_docs" in out
    assert "retrieved_docs" not in out
    rerank = asyncio.run(
        run_rerank_and_validate_context(
            query="Quais são os critérios de inclusão para sgb?",
            expanded_query=rewrite["expanded_query"],
            structured_terms=rewrite["structured_terms"],
            clinical_understanding=rewrite["clinical_understanding"],
            candidate_docs=out["candidate_docs"],
            settings=settings,
        )
    )

    docs = rerank["retrieved_docs"]
    assert len(store.calls) == 1
    assert docs[0].metadata["section"] == "CID-10"
    assert rerank["insufficiency_reason"] == "seção preferencial não encontrada; contexto parcialmente suficiente"


def test_retrieve_node_marks_preferred_section_not_found_after_complementary_search(monkeypatch) -> None:
    monkeypatch.setattr(rag_service, "cached_conitec_catalog", lambda: _catalog())
    first = [
        (
            _doc(
                "G61.0",
                disease="Síndrome de Guillain-Barré",
                diretriz="Síndrome de Guillain-Barré",
                disease_normalized="sindrome de guillain barre",
                section="CID-10",
                cid10_codes=["G61.0"],
            ),
            0.1,
        )
    ]
    store = _FakeStore(first, [])
    settings = Settings(rag_retrieve_candidates_k=10, rag_retrieve_final_k=6)

    rewrite = run_rewrite_query("Quais são os critérios de inclusão para sgb?", {}, settings)
    out = retrieve_node({**rewrite, "query": "Quais são os critérios de inclusão para sgb?"}, store=store, settings=settings)
    rerank = asyncio.run(
        run_rerank_and_validate_context(
            query="Quais são os critérios de inclusão para sgb?",
            expanded_query=rewrite["expanded_query"],
            structured_terms=rewrite["structured_terms"],
            clinical_understanding=rewrite["clinical_understanding"],
            candidate_docs=out["candidate_docs"],
            settings=settings,
        )
    )

    assert len(store.calls) == 1
    assert [doc.metadata["section"] for doc in rerank["retrieved_docs"]] == ["CID-10"]
    assert rerank["insufficiency_reason"] == "seção preferencial não encontrada; contexto parcialmente suficiente"


def test_rerank_documents_boosts_inclusion_section_over_incompatible_sections() -> None:
    expansion = expand_query_with_conitec_catalog(
        "Quais são os critérios de inclusão para artrite reumatoide?",
        _catalog(),
    )
    docs = [
        (
            _doc(
                "tratamento medicamentoso",
                disease="Artrite Reumatoide",
                diretriz="Artrite Reumatoide",
                section="TRATAMENTO",
                cid10_codes=["M05", "M06"],
            ),
            0.1,
        ),
        (
            _doc(
                "serão incluídos pacientes",
                disease="Artrite Reumatoide",
                diretriz="Artrite Reumatoide",
                section="CRITÉRIOS DE INCLUSÃO",
                cid10_codes=["M05", "M06"],
            ),
            0.2,
        ),
    ]

    ranked = rerank_documents("Quais são os critérios de inclusão para artrite reumatoide?", expansion, docs, final_k=2)

    assert ranked[0].metadata["section"] == "CRITÉRIOS DE INCLUSÃO"
    assert "section_intent_match:criterios_inclusao" in ranked[0].metadata["ranking_reasons"]
    assert "penalty_wrong_section:tratamento" in ranked[1].metadata["ranking_reasons"]


def test_rerank_documents_expanded_cid_does_not_dominate_section_intent() -> None:
    expansion = expand_query_with_conitec_catalog(
        "Quais são os critérios de inclusão para artrite reumatoide?",
        _catalog(),
    )
    docs = [
        (
            _doc(
                "M05 M06",
                disease="Artrite Reumatoide",
                diretriz="Artrite Reumatoide",
                section="CID-10",
                cid10_codes=["M05", "M06"],
            ),
            0.1,
        ),
        (
            _doc(
                "serão incluídos pacientes",
                disease="Artrite Reumatoide",
                diretriz="Artrite Reumatoide",
                section="CRITÉRIOS DE INCLUSÃO",
                cid10_codes=[],
            ),
            0.2,
        ),
    ]

    ranked = rerank_documents("Quais são os critérios de inclusão para artrite reumatoide?", expansion, docs, final_k=2)

    assert ranked[0].metadata["section"] == "CRITÉRIOS DE INCLUSÃO"
    assert any(reason.startswith("cid_catalog_hint_ignored:") for reason in ranked[1].metadata["ranking_reasons"])


def test_rerank_documents_treatment_prefers_treatment_sections_over_cid_and_intro() -> None:
    expansion = expand_query_with_conitec_catalog("Qual o melhor tratamento para artrite reumatoide?", _catalog())
    docs = [
        (_doc("cid", disease="Artrite Reumatoide", diretriz="Artrite Reumatoide", section="CID-10", cid10_codes=["M05.0", "M06"]), 0.1),
        (_doc("intro", disease="Artrite Reumatoide", diretriz="Artrite Reumatoide", section="INTRODUÇÃO", cid10_codes=["M05.0", "M06"]), 0.2),
        (_doc("tratamento sintomático", disease="Artrite Reumatoide", diretriz="Artrite Reumatoide", section="Tratamento sintomático", cid10_codes=["M05.0", "M06"]), 0.3),
        (_doc("tratamento", disease="Artrite Reumatoide", diretriz="Artrite Reumatoide", section="TRATAMENTO", cid10_codes=["M05.0", "M06"]), 0.4),
    ]

    ranked = rerank_documents("Qual o melhor tratamento para artrite reumatoide?", expansion, docs, final_k=4)

    assert ranked[0].metadata["section"] in {"TRATAMENTO", "Tratamento sintomático"}
    assert ranked[1].metadata["section"] in {"TRATAMENTO", "Tratamento sintomático"}
    assert ranked[-1].metadata["section"] in {"CID-10", "INTRODUÇÃO"}
    assert not any(
        reason.startswith("cid_catalog_hint:")
        for doc in ranked
        for reason in doc.metadata["ranking_reasons"]
    )
    assert any(
        reason.startswith("cid_catalog_hint_ignored:")
        for doc in ranked
        for reason in doc.metadata["ranking_reasons"]
    )


def test_rerank_documents_explicit_cid_keeps_strong_boost() -> None:
    expansion = expand_query_with_conitec_catalog("O que o PCDT fala sobre M05.0?", _catalog())
    docs = [
        (_doc("texto geral", disease="Artrite Reumatoide", diretriz="Artrite Reumatoide", section="INTRODUÇÃO", cid10_codes=["M06"]), 0.1),
        (_doc("M05.0", disease="Artrite Reumatoide", diretriz="Artrite Reumatoide", section="CID-10", cid10_codes=["M05.0"]), 0.2),
    ]

    ranked = rerank_documents("O que o PCDT fala sobre M05.0?", expansion, docs, final_k=2)

    assert ranked[0].metadata["section"] == "CID-10"
    assert "cid_explicit_match:M05.0" in ranked[0].metadata["ranking_reasons"]


def test_rerank_documents_keeps_juvenile_arthritis_out_of_top_six_for_rheumatoid_query() -> None:
    expansion = expand_query_with_conitec_catalog(
        "Quais são os critérios de inclusão para artrite reumatoide?",
        _catalog(),
    )
    docs = [
        (
            _doc(
                "aij critérios",
                disease="Artrite Idiopática Juvenil",
                diretriz="Artrite Idiopática Juvenil",
                section="CRITÉRIOS DE INCLUSÃO",
            ),
            0.01,
        ),
        *[
            (
                _doc(
                    f"artrite reumatoide {section}",
                    disease="Artrite Reumatoide",
                    diretriz="Artrite Reumatoide",
                    section=section,
                ),
                0.2 + idx,
            )
            for idx, section in enumerate(
                [
                    "CRITÉRIOS DE INCLUSÃO",
                    "INTRODUÇÃO",
                    "CLASSIFICAÇÃO",
                    "MONITORAMENTO",
                    "DIAGNÓSTICO",
                    "CRITÉRIOS DE EXCLUSÃO",
                ]
            )
        ],
    ]

    ranked = rerank_documents("Quais são os critérios de inclusão para artrite reumatoide?", expansion, docs, final_k=6)

    assert ranked[0].metadata["diretriz"] == "Artrite Reumatoide"
    assert ranked[0].metadata["section"] == "CRITÉRIOS DE INCLUSÃO"
    assert all(doc.metadata["diretriz"] != "Artrite Idiopática Juvenil" for doc in ranked)


def test_disease_filter_keeps_only_detected_disease() -> None:
    understanding = understand_clinical_query("Quais são os critérios de inclusão para artrite reumatóide?", _catalog())
    docs = [
        (_doc("cid", disease_normalized="artrite reumatoide", disease="Artrite Reumatoide", section="CID-10"), 0.1),
        (_doc("inclui", disease_normalized="artrite reumatoide", disease="Artrite Reumatoide", section="CRITÉRIOS DE INCLUSÃO"), 0.2),
        (_doc("aij", disease_normalized="artrite idiopatica juvenil", disease="Artrite Idiopática Juvenil", section="INTRODUÇÃO"), 0.3),
        (_doc("mps", disease_normalized="mucopolissacaridose", disease="Mucopolissacaridose", section="CRITÉRIOS DE INCLUSÃO"), 0.4),
    ]

    filtered, info = filter_documents_by_detected_disease(docs, understanding)

    assert info["disease_filter_applied"] is True
    assert info["candidate_count_before_filter"] == 4
    assert info["candidate_count_after_filter"] == 2
    assert all(_doc_obj.metadata["disease"] == "Artrite Reumatoide" for _doc_obj, _score in filtered)


def test_rerank_documents_filters_wrong_diseases_and_prefers_inclusion_section() -> None:
    query = "Quais são os critérios de inclusão para artrite reumatóide?"
    expansion = expand_query_with_conitec_catalog(query, _catalog())
    docs = [
        (_doc("cid", disease_normalized="artrite reumatoide", disease="Artrite Reumatoide", diretriz="Artrite Reumatoide", section="CID-10"), 0.1),
        (_doc("fármacos", disease_normalized="artrite reumatoide", disease="Artrite Reumatoide", diretriz="Artrite Reumatoide", section="FÁRMACOS"), 0.2),
        (_doc("tratamento", disease_normalized="artrite reumatoide", disease="Artrite Reumatoide", diretriz="Artrite Reumatoide", section="TRATAMENTO"), 0.3),
        (_doc("inclui", disease_normalized="artrite reumatoide", disease="Artrite Reumatoide", diretriz="Artrite Reumatoide", section="CRITÉRIOS DE INCLUSÃO"), 0.4),
        (_doc("aij", disease_normalized="artrite idiopatica juvenil", disease="Artrite Idiopática Juvenil", diretriz="Artrite Idiopática Juvenil", section="INTRODUÇÃO"), 0.5),
        (_doc("mps", disease_normalized="mucopolissacaridose", disease="Mucopolissacaridose", diretriz="Mucopolissacaridose", section="CRITÉRIOS DE INCLUSÃO"), 0.6),
    ]

    ranked = rerank_documents(query, expansion, docs, final_k=6)

    assert ranked[0].metadata["section"] == "CRITÉRIOS DE INCLUSÃO"
    assert ranked[0].metadata["disease"] == "Artrite Reumatoide"
    assert "disease_exact_match:artrite_reumatoide" in ranked[0].metadata["ranking_reasons"]
    assert "section_intent_match:criterios_inclusao" in ranked[0].metadata["ranking_reasons"]
    assert "combined_disease_section_match" in ranked[0].metadata["ranking_reasons"]
    assert all(doc.metadata["disease"] == "Artrite Reumatoide" for doc in ranked)
    assert ranked[0].metadata["section"] != "CID-10"


def test_rerank_documents_does_not_add_contradictory_disease_reasons_on_filter_fallback() -> None:
    query = "Quais são os critérios de inclusão para artrite reumatóide?"
    expansion = expand_query_with_conitec_catalog(query, _catalog())
    docs = [
        (
            _doc(
                "aij",
                disease_normalized="artrite idiopatica juvenil aij",
                disease="Artrite Idiopática Juvenil",
                diretriz="Artrite Idiopática Juvenil",
                section="CRITÉRIOS DE INCLUSÃO",
            ),
            0.1,
        )
    ]

    ranked = rerank_documents(query, expansion, docs, final_k=1, min_final_score=-100.0)
    reasons = ranked[0].metadata["ranking_reasons"]

    assert not any(reason.startswith("disease_exact_match:") for reason in reasons)
    assert "penalty_wrong_disease:artrite_idiopatica_juvenil" in reasons


def test_cross_encoder_fallback_without_model(monkeypatch) -> None:
    monkeypatch.setattr(ce_mod, "load_cross_encoder_model", lambda _model_name: None)
    docs = [_doc("a", final_score=1.0), _doc("b", final_score=0.5)]

    reranked = apply_cross_encoder_rerank("q", docs, model_name="missing")

    assert reranked == docs


def test_cross_encoder_combines_scores_with_mock_model() -> None:
    class _Model:
        def predict(self, _pairs):
            return [0.1, 0.9]

    docs = [
        _doc("baixo cross", final_score=1.0, ranking_reasons=[]),
        _doc("alto cross", final_score=1.0, ranking_reasons=[]),
    ]

    reranked = apply_cross_encoder_rerank("q", docs, model_name="mock", model=_Model())

    assert reranked[0].page_content == "alto cross"
    assert reranked[0].metadata["cross_encoder_score"] == 0.9
    assert "cross_encoder_rerank" in reranked[0].metadata["ranking_reasons"]


def test_format_context_document_includes_metadata_and_limits_medications() -> None:
    doc = _doc(
        "Trecho clínico.",
        diretriz="Insuficiência Adrenal",
        disease="Insuficiência Adrenal",
        cid10_codes=["E27.1"],
        medicamentos=[f"Medicamento {i}" for i in range(15)],
        section="CRITÉRIOS DE INCLUSÃO",
        page_start=6,
        page_end=6,
    )

    formatted = format_context_document(doc, 1)

    assert "Diretriz: Insuficiência Adrenal" in formatted
    assert "CID-10: E27.1" in formatted
    assert "Seção: CRITÉRIOS DE INCLUSÃO" in formatted
    assert "Páginas: 6-6" in formatted
    assert "Medicamento 9" in formatted
    assert "Medicamento 10" not in formatted
    assert "..." in formatted


def test_format_context_document_handles_missing_metadata() -> None:
    formatted = format_context_document(_doc("Texto."), 1)

    assert "Diretriz: -" in formatted
    assert "Trecho:\nTexto." in formatted


def test_append_audit_jsonl_write(tmp_path: Path) -> None:
    payload = {"question": "Paciente com E27.1", "structured_terms": {"cid10_codes": ["E27.1"]}}
    append_audit_jsonl(payload, tmp_path / "audit.jsonl")

    line = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert parsed["question"] == "Paciente com E27.1"
    assert "structured_terms" in parsed


def test_expansion_is_json_serializable_and_keeps_structured_terms_out_of_chroma_text() -> None:
    expanded = expand_query_with_conitec_catalog("Quais são os critérios de inclusão para sgb?", _catalog())

    json.dumps(expanded, ensure_ascii=False)
    json.dumps(expanded["structured_terms"], ensure_ascii=False)
    _assert_clean_expanded_query(expanded["expanded_query"])
    assert expanded["structured_terms"]["catalog_candidates"]


def test_hiv_pediatric_expansion_has_catalog_candidates_and_not_only_intent() -> None:
    expanded = expand_query_with_conitec_catalog("Como tratar HIV em crianças?", _catalog())

    assert "Manejo da Infecção pelo HIV em Crianças e Adolescentes" in expanded["expanded_query"]
    assert "TRATAMENTO" in expanded["expanded_query"]
    assert expanded["expanded_query"] != "Como tratar HIV em crianças? TRATAMENTO"
    assert expanded["structured_terms"]["catalog_candidates"]
    _assert_clean_expanded_query(expanded["expanded_query"])


def test_chat_retrieve_sgb_uses_catalog_expansion(monkeypatch) -> None:
    monkeypatch.setattr(rag_service, "cached_conitec_catalog", lambda: _catalog())
    sgb_doc = _doc(
        "Serão incluídos pacientes com Síndrome de Guillain-Barré.",
        disease="Síndrome de Guillain-Barré",
        diretriz="Síndrome de Guillain-Barré",
        disease_normalized="sindrome de guillain barre",
        section="CRITÉRIOS DE INCLUSÃO",
        cid10_codes=["G61.0"],
        source_stem="20201022_portaria_conjunta_pcdt_sgb-1",
    )
    wrong_doc = _doc(
        "Critérios de inclusão de outra doença.",
        disease="Doença de Paget",
        diretriz="Doença de Paget",
        disease_normalized="doenca de paget",
        section="CRITÉRIOS DE INCLUSÃO",
        source_stem="pcdt-paget",
    )
    store = _FakeStore([(wrong_doc, 0.1), (sgb_doc, 0.2)])
    settings = Settings(rag_retrieve_candidates_k=10, rag_retrieve_final_k=6)

    rewrite = run_rewrite_query("Quais são os critérios de inclusão para sgb?", {}, settings)
    out = retrieve_node({**rewrite, "query": "Quais são os critérios de inclusão para sgb?"}, store=store, settings=settings)
    rerank = asyncio.run(
        run_rerank_and_validate_context(
            query="Quais são os critérios de inclusão para sgb?",
            expanded_query=rewrite["expanded_query"],
            structured_terms=rewrite["structured_terms"],
            clinical_understanding=rewrite["clinical_understanding"],
            candidate_docs=out["candidate_docs"],
            settings=settings,
        )
    )

    docs = rerank["retrieved_docs"]
    assert "Síndrome de Guillain-Barré" in rewrite["expanded_query"]
    assert rewrite["structured_terms"]["disease"] == "Síndrome de Guillain-Barré"
    assert "G61.0" in rewrite["structured_terms"]["cid10_codes"]
    assert rewrite["structured_terms"]["intent"] == "criterios_inclusao"
    assert [doc.metadata["disease"] for doc in docs] == ["Síndrome de Guillain-Barré"]


def test_chat_and_inspector_use_same_retrieval_service() -> None:
    retrieve_source = inspect.getsource(retrieve_node)
    inspector_source = (Path(__file__).resolve().parents[2] / "llm" / "scripts" / "rag_inspector_app.py").read_text(
        encoding="utf-8"
    )

    assert "run_retrieve" in retrieve_source
    assert "run_full_graph_debug" in inspector_source
    assert "retrieve_node(" not in inspector_source
    assert "--export-audit" in inspector_source


def test_generate_does_not_reinterpret_detected_abbreviation() -> None:
    state = {
        "query": "Quais são os critérios de inclusão para sgb?",
        "retrieved_docs": [
            _doc(
                "Critérios de inclusão para SGB.",
                disease="Síndrome de Guillain-Barré",
                diretriz="Síndrome de Guillain-Barré",
                disease_normalized="sindrome de guillain barre",
                section="CRITÉRIOS DE INCLUSÃO",
            )
        ],
        "query_expansion": {
            "expanded_query": "Quais são os critérios de inclusão para sgb? Síndrome de Guillain-Barré G61.0 CRITÉRIOS DE INCLUSÃO",
            "structured_terms": {
                "disease": "Síndrome de Guillain-Barré",
                "diretriz": "Síndrome de Guillain-Barré",
                "disease_normalized": "sindrome de guillain barre",
                "cid10_codes": ["G61.0"],
                "intent": "criterios_inclusao",
                "preferred_sections": ["CRITÉRIOS DE INCLUSÃO"],
            },
        },
        "clinical_understanding": {},
    }

    prompt = "\n".join(str(message.content) for message in _build_messages(state))

    assert "Doença: Síndrome de Guillain-Barré" in prompt
    assert "Diretriz: Síndrome de Guillain-Barré" in prompt
    assert "Síndrome de Sobrecarga de Glóbulos Brancos" not in prompt


def test_no_context_mismatch_goes_to_llm() -> None:
    state = {
        "query": "Quais são os critérios de inclusão para sgb?",
        "retrieved_docs": [
            _doc(
                "Critérios de inclusão de Doença de Wilson.",
                disease="Doença de Wilson",
                diretriz="Doença de Wilson",
                disease_normalized="doenca de wilson",
                section="CRITÉRIOS DE INCLUSÃO",
            )
        ],
        "query_expansion": {
            "expanded_query": "Quais são os critérios de inclusão para sgb? Síndrome de Guillain-Barré G61.0 CRITÉRIOS DE INCLUSÃO",
            "structured_terms": {
                "disease": "Síndrome de Guillain-Barré",
                "diretriz": "Síndrome de Guillain-Barré",
                "disease_normalized": "sindrome de guillain barre",
                "cid10_codes": ["G61.0"],
                "intent": "criterios_inclusao",
            },
        },
        "clinical_understanding": {},
    }

    out = asyncio.run(generate_node(state, Settings()))

    assert "Não encontrei trechos PCDT compatíveis com Síndrome de Guillain-Barré" in out["answer"]
