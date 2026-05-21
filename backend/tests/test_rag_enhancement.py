from __future__ import annotations

import json
from pathlib import Path

from langchain_core.documents import Document

from assistente_medico_api.graph.rag_enhancement import (
    append_audit_jsonl,
    build_audit_payload,
    expand_query_with_conitec_catalog,
    extract_query_entities,
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
    }


def _doc(text: str, **metadata) -> Document:
    return Document(page_content=text, metadata=metadata)


def test_extract_query_entities_detects_cid_and_intent() -> None:
    entities = extract_query_entities("Quais critérios de inclusão para E27.1?", _catalog())

    assert entities["cid10_codes"] == ["E27.1"]
    assert entities["section_intent"] == "criterios_inclusao"


def test_extract_query_entities_detects_treatment_and_empty_query() -> None:
    assert extract_query_entities("tratamento com hidrocortisona", _catalog())["section_intent"] == "tratamento"
    empty = extract_query_entities("", _catalog())
    assert empty["cid10_codes"] == []
    assert empty["section_intent"] is None


def test_expand_query_with_conitec_catalog_expands_disease_to_cid_and_medication() -> None:
    expanded = expand_query_with_conitec_catalog("critérios para insuficiência adrenal", _catalog(), max_terms=10)

    assert "Insuficiência Adrenal" in expanded["matched_diseases"]
    assert "E27.1" in expanded["matched_cid10_codes"]
    assert any("Prednisona" in med for med in expanded["matched_medications"])
    assert "E23.0" in expanded["expanded_query"]


def test_expand_query_with_conitec_catalog_expands_cid_to_diretriz() -> None:
    expanded = expand_query_with_conitec_catalog("Paciente com E75.4", _catalog(), max_terms=8)

    assert expanded["matched_diseases"] == ["Lipofuscinose Ceroide Neuronal tipo 2"]
    assert "Lipofuscinose neuronal ceroide" in expanded["expanded_query"]


def test_expand_query_with_conitec_catalog_fallback_and_max_terms() -> None:
    expanded = expand_query_with_conitec_catalog("doença desconhecida", _catalog(), max_terms=2)

    assert expanded["expanded_query"] == "doença desconhecida"
    assert expanded["matched_terms"] == []

    expanded_known = expand_query_with_conitec_catalog("insuficiência adrenal", _catalog(), max_terms=2)
    assert len(expanded_known["matched_terms"]) <= 2


def test_rerank_documents_boosts_exact_cid_and_preserves_scores() -> None:
    expansion = expand_query_with_conitec_catalog("Paciente com E27.1", _catalog())
    docs = [
        (_doc("texto geral", source_stem="x", cid10_codes=["A00"], section="INTRODUÇÃO"), 0.1),
        (_doc("texto E27.1", source_stem="ia", cid10_codes=["E27.1"], section="DIAGNÓSTICO"), 0.9),
    ]

    ranked = rerank_documents("Paciente com E27.1", expansion, docs, final_k=2)

    assert ranked[0].metadata["source_stem"] == "ia"
    assert ranked[0].metadata["dense_score"] == 0.9
    assert any(reason == "cid10_match:E27.1" for reason in ranked[0].metadata["ranking_reasons"])


def test_rerank_documents_boosts_section_and_penalizes_admin() -> None:
    expansion = expand_query_with_conitec_catalog("critérios de inclusão para insuficiência adrenal", _catalog())
    docs = [
        (_doc("texto administrativo", disease="Insuficiência Adrenal", section="REGULAÇÃO/CONTROLE/AVALIAÇÃO PELO GESTOR"), 0.1),
        (_doc("serão incluídos", disease="Insuficiência Adrenal", section="CRITÉRIOS DE INCLUSÃO"), 0.2),
    ]

    ranked = rerank_documents("critérios de inclusão para insuficiência adrenal", expansion, docs, final_k=2)

    assert ranked[0].metadata["section"] == "CRITÉRIOS DE INCLUSÃO"
    assert any("section_match:criterios_inclusao" == reason for reason in ranked[0].metadata["ranking_reasons"])
    assert any("penalty:administrative_section" == reason for reason in ranked[1].metadata["ranking_reasons"])


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
