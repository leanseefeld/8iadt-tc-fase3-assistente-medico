from __future__ import annotations

import json
from pathlib import Path

from langchain_core.documents import Document

from assistente_medico_api.graph import cross_encoder_reranker as ce_mod
from assistente_medico_api.graph.clinical_query_understanding import (
    CatalogCandidateRetriever,
    detect_clinical_intent,
    expand_query_for_medical_chat,
    match_disease_from_catalog,
    understand_clinical_query,
)
from assistente_medico_api.graph.cross_encoder_reranker import apply_cross_encoder_rerank
from assistente_medico_api.graph.rag_enhancement import (
    append_audit_jsonl,
    build_audit_payload,
    expand_query_with_conitec_catalog,
    extract_query_entities,
    filter_documents_by_detected_disease,
    format_context_document,
    rerank_documents,
)


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
            "cid10_codes": ["M05", "M06"],
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
    }


def _doc(text: str, **metadata) -> Document:
    return Document(page_content=text, metadata=metadata)


def test_detect_clinical_intent_minimum_cases() -> None:
    assert detect_clinical_intent("Quais são os critérios de inclusão para artrite reumatoide?") == "criterios_inclusao"
    assert detect_clinical_intent("Qual tratamento para asma?") == "tratamento"
    assert detect_clinical_intent("Como monitorar insuficiência adrenal?") == "monitoramento"


def test_match_disease_from_catalog_is_restrictive() -> None:
    assert match_disease_from_catalog("artrite reumatoide", _catalog())["name"] == "Artrite Reumatoide"
    assert match_disease_from_catalog("artrite idiopática juvenil", _catalog())["name"] == "Artrite Idiopática Juvenil"
    assert match_disease_from_catalog("artrite", _catalog()) is None
    assert match_disease_from_catalog("asma", _catalog())["name"] == "Asma"


def test_catalog_candidate_retriever_uses_full_catalog_fields_for_hiv_pediatric_query() -> None:
    candidates = CatalogCandidateRetriever(_catalog()).search("Como tratar HIV em crianças?", limit=5)

    assert candidates
    assert candidates[0].disease == "Infecção pelo HIV em Crianças e Adolescentes"
    assert "diretriz" in candidates[0].matched_fields or "source_stem" in candidates[0].matched_fields
    weak_names = {candidate.disease for candidate in candidates[1:]}
    assert "Artrite Idiopática Juvenil" not in weak_names
    assert "Mucopolissacaridose" not in weak_names


def test_match_disease_from_catalog_detects_cid_from_catalog() -> None:
    match = match_disease_from_catalog("O que o PCDT diz sobre E27.1?", _catalog())

    assert match is not None
    assert match["name"] == "Insuficiência Adrenal"
    assert "cid10_codes" in match["catalog_candidate"]["matched_fields"]


def test_understand_clinical_query_fallback_without_catalog() -> None:
    understanding = understand_clinical_query("O que o PCDT diz sobre E27.1?", None)

    assert understanding["original_query"] == "O que o PCDT diz sobre E27.1?"
    assert understanding["detected_cid10_codes"] == ["E27.1"]
    assert understanding["detected_disease"] is None


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

    assert "Insuficiência Adrenal" in expanded["matched_diseases"]
    assert "E27.1" in expanded["matched_cid10_codes"]
    assert expanded["matched_medications"] == []
    assert "E23.0" not in expanded["expanded_query"]


def test_expand_query_with_conitec_catalog_includes_medications_for_treatment_intent() -> None:
    expanded = expand_query_with_conitec_catalog("tratamento para insuficiência adrenal", _catalog(), max_terms=10)

    assert "Insuficiência Adrenal" in expanded["matched_diseases"]
    assert any("Prednisona" in med for med in expanded["matched_medications"])


def test_expand_query_with_conitec_catalog_expands_cid_to_diretriz() -> None:
    expanded = expand_query_with_conitec_catalog("Paciente com E75.4", _catalog(), max_terms=8)

    assert expanded["matched_diseases"] == ["Lipofuscinose Ceroide Neuronal tipo 2"]
    assert "Lipofuscinose Ceroide Neuronal tipo 2" in expanded["expanded_query"]


def test_expand_query_with_conitec_catalog_fallback_and_max_terms() -> None:
    expanded = expand_query_with_conitec_catalog("doença desconhecida", _catalog(), max_terms=2)

    assert expanded["expanded_query"] == "doença desconhecida"
    assert expanded["matched_terms"] == []

    expanded_known = expand_query_with_conitec_catalog("insuficiência adrenal", _catalog(), max_terms=2)
    assert len(expanded_known["matched_terms"]) <= 2


def test_expand_query_with_conitec_catalog_is_restrictive_for_rheumatoid_arthritis() -> None:
    expanded = expand_query_with_conitec_catalog(
        "Quais são os critérios de inclusão para artrite reumatoide?",
        _catalog(),
        max_terms=20,
    )

    assert expanded["matched_diseases"] == ["Artrite Reumatoide"]
    assert expanded["matched_medications"] == []
    assert "Artrite Reumatoide" in expanded["expanded_query"]
    assert "CRITÉRIOS DE INCLUSÃO" in expanded["expanded_query"]
    assert "M05" not in expanded["expanded_query"]
    assert "M06" not in expanded["expanded_query"]
    assert "Metotrexato" not in expanded["expanded_query"]
    assert "Artrite Idiopática Juvenil" not in expanded["expanded_query"]
    assert "Asma" not in expanded["expanded_query"]


def test_expand_query_for_medical_chat_respects_max_terms_and_fallback() -> None:
    understanding = understand_clinical_query("Quais são os critérios de inclusão para artrite reumatoide?", _catalog())
    expanded = expand_query_for_medical_chat(understanding, _catalog(), max_terms=3)

    assert len(expanded["added_terms"]) <= 3
    assert expanded["expanded_query"].startswith("Quais são os critérios")

    fallback = expand_query_for_medical_chat(understand_clinical_query("doença desconhecida", None), None)
    assert fallback["expanded_query"] == "doença desconhecida"
    assert fallback["added_terms"] == []


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
    assert any(reason.startswith("cid_expansion_hint_ignored:") for reason in ranked[1].metadata["ranking_reasons"])


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


def test_build_audit_payload_and_jsonl_write(tmp_path: Path) -> None:
    expansion = expand_query_with_conitec_catalog("Paciente com E27.1", _catalog())
    doc = _doc("texto", source_stem="s", source_pdf="raw/s.pdf", cid10_codes='["E27.1"]')

    payload = build_audit_payload(
        question="Paciente com E27.1",
        expansion=expansion,
        documents=[doc],
        retrieval_candidates_k=30,
        retrieval_final_k=6,
        answer="resposta",
    )
    append_audit_jsonl(payload, tmp_path / "audit.jsonl")

    line = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert parsed["question"] == "Paciente com E27.1"
    assert parsed["documents"][0]["source_stem"] == "s"
    assert parsed["documents"][0]["cid10_codes"] == ["E27.1"]
