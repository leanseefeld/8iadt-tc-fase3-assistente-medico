"""Helpers puros para expansão, reranking, contexto e auditoria RAG."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from langchain_core.documents import Document

from assistente_medico_api.graph.cross_encoder_reranker import apply_cross_encoder_rerank
from assistente_medico_api.graph.clinical_query_understanding import (
    INTENT_SECTION_LABELS,
    expand_query_for_medical_chat,
    normalize_text_for_match,
    understand_clinical_query,
)
from assistente_medico_api.graph.clinical_query_understanding import (
    _char_ngram_embedding,
    _cosine_similarity,
)

try:
    from pcdt_ingest.paths import data_root
    from pcdt_ingest.reference_data.conitec_catalog import (
        DEFAULT_CATALOG_RELATIVE_PATH,
        read_catalog_jsonl,
    )
except Exception:  # pragma: no cover - backend pode ser importado sem pacote llm instalado.
    data_root = None  # type: ignore[assignment]
    DEFAULT_CATALOG_RELATIVE_PATH = Path("processed/conitec/pcdt_catalog.jsonl")

    def read_catalog_jsonl(_path: Path) -> dict[str, dict[str, Any]]:  # type: ignore[no-redef]
        return {}


_TREATMENT_INTENTS = {"tratamento", "dose", "medicamento"}
_INTENT_SECTION_NORMS = {intent: normalize_text_for_match(label) for intent, label in INTENT_SECTION_LABELS.items()}
_TREATMENT_SECTION_HINTS = {
    normalize_text_for_match(value)
    for value in ("TRATAMENTO", "TRATAMENTO MEDICAMENTOSO", "FÁRMACOS", "ESQUEMAS")
}

# Legacy section-penalty lists are intentionally left empty to avoid
# hard-coded clinical token rules dominating ranking. The catalog and
# detected entities should guide retrieval; any section-level signals
# must be lightweight and learned/derived rather than hardcoded.
SECTION_PENALTIES_BY_INTENT: dict[str, dict[str, float]] = {}

# Administrative sections are not universally harmful; keep this map
# empty to avoid removing relevant documents based on brittle lists.
ADMIN_SECTION_PENALTIES: dict[str, float] = {}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                decoded = json.loads(text)
                if isinstance(decoded, list):
                    return [str(item).strip() for item in decoded if str(item).strip()]
            except Exception:
                return [text]
        return [text]
    return [str(value).strip()] if str(value).strip() else []


def _dedupe(values: Iterable[Any], *, limit: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = normalize_text_for_match(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if limit is not None and len(out) >= limit:
            break
    return out


def _public_catalog_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "diretriz": candidate.get("diretriz"),
        "disease": candidate.get("disease"),
        "score": float(candidate.get("score") or 0.0),
        "matched_fields": _as_list(candidate.get("matched_fields")),
        "reasons": _as_list(candidate.get("reasons")),
        "source": candidate.get("source") or "catalog_semantic",
    }


def _build_structured_terms(
    *,
    understanding: dict[str, Any],
    matched_entries: list[dict[str, Any]],
    matched_cids: list[str],
    cid_descriptions: list[str],
    matched_meds: list[str],
) -> dict[str, Any]:
    disease = understanding.get("detected_disease") or {}
    best_entry = matched_entries[0] if matched_entries else {}
    intent = understanding.get("intent") or (understanding.get("intent_result") or {}).get("intent")
    preferred_sections = _dedupe([INTENT_SECTION_LABELS.get(str(intent))] if intent in INTENT_SECTION_LABELS else [])
    candidate_confidences = [
        float(candidate.get("score") or 0.0)
        for candidate in understanding.get("catalog_candidates") or []
    ]
    confidence = max(candidate_confidences or [float(disease.get("confidence") or 0.0)])
    return {
        "disease": best_entry.get("disease") or disease.get("name"),
        "disease_normalized": normalize_text_for_match(
            best_entry.get("disease_normalized") or disease.get("normalized") or disease.get("name") or ""
        )
        or None,
        "diretriz": best_entry.get("diretriz") or best_entry.get("disease") or disease.get("name"),
        "cid10_codes": _dedupe(matched_cids),
        "cid10_descriptions": _dedupe(cid_descriptions),
        "medications": _dedupe(matched_meds),
        "intent": intent,
        "preferred_sections": preferred_sections,
        "catalog_candidates": [
            _public_catalog_candidate(candidate)
            for candidate in understanding.get("catalog_candidates") or []
        ],
        "linked_entities": [
            dict(entity)
            for entity in understanding.get("linked_entities") or []
            if isinstance(entity, dict)
        ],
        "confidence": round(float(confidence or 0.0), 4),
    }


def _expanded_query_terms(
    *,
    structured_terms: dict[str, Any],
    original_added_terms: list[str],
    max_terms: int,
) -> list[str]:
    terms: list[str] = []
    diretriz = structured_terms.get("diretriz")
    disease = structured_terms.get("disease")
    has_catalog_candidate = bool(structured_terms.get("catalog_candidates"))
    if diretriz:
        terms.append(str(diretriz))
    elif disease:
        terms.append(str(disease))

    cid10_codes = _as_list(structured_terms.get("cid10_codes"))
    if len(cid10_codes) == 1:
        terms.append(cid10_codes[0])

    if has_catalog_candidate:
        terms.extend(_as_list(structured_terms.get("preferred_sections")))

    # Preserve any existing conservative catalog-derived terms that are not
    # field labels or serialized structures.
    terms.extend(term for term in original_added_terms if not _looks_structured(term))
    return _dedupe(terms, limit=max_terms)


def _preferred_section_norms(intent: Any, structured_terms: dict[str, Any]) -> list[str]:
    preferred = [
        normalize_text_for_match(section)
        for section in _as_list(structured_terms.get("preferred_sections"))
    ]
    if str(intent) == "tratamento":
        preferred.extend(sorted(_TREATMENT_SECTION_HINTS))
    expected = _INTENT_SECTION_NORMS.get(str(intent))
    if expected:
        preferred.append(expected)
    return _dedupe(preferred)


def _section_text_norm(metadata: dict[str, Any]) -> str:
    return normalize_text_for_match(
        " ".join(_as_list(metadata.get("section")) + _as_list(metadata.get("header_1")) + _as_list(metadata.get("header_2")))
    )


def _document_has_preferred_section(item: Any, preferred_sections: list[str]) -> bool:
    if not preferred_sections:
        return False
    doc, _score = _doc_from_pair(item)
    section_norm = _section_text_norm(dict(getattr(doc, "metadata", {}) or {}))
    return any(section and section in section_norm for section in preferred_sections)


def _document_pair_key(item: Any) -> tuple[str, str, str, str]:
    doc, _score = _doc_from_pair(item)
    metadata = dict(getattr(doc, "metadata", {}) or {})
    return (
        str(getattr(doc, "id", "") or ""),
        str(metadata.get("source_stem") or metadata.get("source_pdf") or ""),
        str(metadata.get("page_start") or ""),
        normalize_text_for_match(str(getattr(doc, "page_content", "") or "")[:500]),
    )


def merge_retrieval_pairs(primary: list[Any], complementary: list[Any]) -> list[Any]:
    """Merge Chroma result pairs preserving order and removing duplicate chunks."""
    merged: list[Any] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in [*primary, *complementary]:
        key = _document_pair_key(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def build_complementary_retrieve_plan(
    *,
    query: str,
    expansion: dict[str, Any],
    documents: list[Any],
    final_k: int,
) -> dict[str, Any]:
    """Decide whether a disease/section-focused second retrieval is needed."""
    understanding = expansion.get("clinical_understanding") or {}
    structured = expansion.get("structured_terms") or {}
    intent = structured.get("intent") or understanding.get("intent")
    preferred_sections = _preferred_section_norms(intent, structured)
    filtered_docs, filter_info = filter_documents_by_detected_disease(
        documents,
        understanding,
        structured_terms=structured,
    )
    preferred_section_found = any(_document_has_preferred_section(item, preferred_sections) for item in filtered_docs)
    has_confident_catalog_candidate = bool(filter_info.get("has_confident_catalog_candidate"))
    should_run = bool(
        has_confident_catalog_candidate
        and preferred_sections
        and (len(filtered_docs) < max(2, min(final_k, 4)) or not preferred_section_found)
    )
    disease = structured.get("diretriz") or structured.get("disease") or ""
    section_terms = _as_list(structured.get("preferred_sections"))
    if str(intent) == "tratamento":
        section_terms.extend(["Tratamento medicamentoso", "Fármacos", "Esquemas"])
    complementary_query = _compose_expanded_query(
        "",
        _dedupe([disease, *section_terms, query], limit=8),
    )
    disease_norm = _structured_disease_norm(structured, understanding)
    return {
        "should_run": should_run,
        "query": complementary_query,
        "metadata_filter": {"disease_normalized": disease_norm} if disease_norm else None,
        "preferred_sections": preferred_sections,
        "preferred_section_found_before": preferred_section_found,
        "documents_after_catalog_filter_before": len(filtered_docs),
        "initial_filter_info": filter_info,
    }


def apply_complementary_retrieve_info(
    expansion: dict[str, Any],
    *,
    plan: dict[str, Any],
    complementary_pairs: list[Any],
    merged_pairs: list[Any],
) -> None:
    understanding = expansion.get("clinical_understanding") or {}
    structured = expansion.get("structured_terms") or {}
    filtered_docs, filter_info = filter_documents_by_detected_disease(
        merged_pairs,
        understanding,
        structured_terms=structured,
    )
    preferred_sections = _as_list(plan.get("preferred_sections"))
    preferred_section_found = any(_document_has_preferred_section(item, preferred_sections) for item in filtered_docs)
    expansion["_complementary_retrieve_info"] = {
        "used": bool(plan.get("should_run")),
        "query": plan.get("query") or "",
        "metadata_filter": plan.get("metadata_filter"),
        "documents_from_complementary_search": len(complementary_pairs),
        "documents_after_complementary_merge": len(merged_pairs),
        "documents_after_catalog_filter": len(filtered_docs),
        "preferred_section_found": preferred_section_found,
        "preferred_section_not_found": bool(preferred_sections and not preferred_section_found),
        "preferred_section_found_before": bool(plan.get("preferred_section_found_before", False)),
    }
    expansion["_catalog_filter_info"] = {
        **filter_info,
        "preferred_section_found": preferred_section_found,
        "preferred_section_not_found": bool(preferred_sections and not preferred_section_found),
    }


def _looks_structured(value: Any) -> bool:
    text = str(value or "").strip()
    return any(marker in text for marker in ("{", "}", "[", "]", ":", '"'))


def _compose_expanded_query(original: str, added_terms: list[str]) -> str:
    clean_terms = [term for term in added_terms if not _looks_structured(term)]
    return f"{original} {' '.join(clean_terms)}".strip() if clean_terms else original


def load_local_conitec_catalog(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Carrega o catálogo local processado; nunca baixa a planilha em runtime."""
    if path is None:
        if data_root is None:
            return {}
        path = data_root() / DEFAULT_CATALOG_RELATIVE_PATH
    if not path.is_file():
        return {}
    return read_catalog_jsonl(path)


def _catalog_entries(catalog: Any) -> list[dict[str, Any]]:
    if not catalog:
        return []
    if isinstance(catalog, dict):
        return [entry for entry in catalog.values() if isinstance(entry, dict)]
    if isinstance(catalog, list):
        return [entry for entry in catalog if isinstance(entry, dict)]
    return []


def extract_query_entities(query: str, catalog: Any | None = None) -> dict[str, Any]:
    """Extrai entidades simples da pergunta sem depender de LLM."""
    understanding = understand_clinical_query(query, catalog)
    disease = understanding.get("detected_disease") or {}
    medication_terms = [str(item.get("name") or "") for item in understanding.get("detected_medications") or []]

    return {
        "cid10_codes": _dedupe(understanding.get("detected_cid10_codes") or []),
        "disease_terms": _dedupe([disease.get("name")] if disease else []),
        "medication_terms": _dedupe(medication_terms),
        "section_intent": None if not query.strip() else understanding.get("intent"),
    }


def expand_query_with_conitec_catalog(query: str, catalog: Any, max_terms: int = 10) -> dict[str, Any]:
    """Expande a query do chat médico de forma restritiva e compatível com o backend."""
    original = (query or "").strip()
    if not original or not catalog:
        understanding = understand_clinical_query(original, catalog)
        structured_terms = _build_structured_terms(
            understanding=understanding,
            matched_entries=[],
            matched_cids=[],
            cid_descriptions=[],
            matched_meds=[],
        )
        return {
            "original_query": original,
            "expanded_query": original,
            "structured_terms": structured_terms,
            "added_terms": [],
            "source": "catalog_candidates",
            "expansion_reason": [],
            "intent": understanding.get("intent_result") or {},
            "linked_entities": understanding.get("linked_entities") or [],
            "catalog_candidates": understanding.get("catalog_candidates") or [],
            "matched_diseases": [],
            "matched_cid10_codes": [],
            "matched_medications": [],
            "matched_terms": [],
            "entities": extract_query_entities(original, catalog),
            "clinical_understanding": understanding,
        }

    understanding = understand_clinical_query(original, catalog)
    expansion = expand_query_for_medical_chat(understanding, catalog, max_terms=max_terms)
    disease = understanding.get("detected_disease") or {}
    disease_norm = normalize_text_for_match(disease.get("normalized") or disease.get("name") or "")
    matched_entries = [
        entry
        for entry in _catalog_entries(catalog)
        if disease_norm
        and normalize_text_for_match(entry.get("disease_normalized") or entry.get("disease") or entry.get("diretriz") or "")
        == disease_norm
    ]

    matched_diseases = _dedupe(entry.get("disease") or entry.get("diretriz") for entry in matched_entries)
    matched_cids = _dedupe(code for entry in matched_entries for code in _as_list(entry.get("cid10_codes")))
    descriptions = _dedupe(desc for entry in matched_entries for desc in _as_list(entry.get("cid10_descriptions")))
    entities = extract_query_entities(original, catalog)
    explicit_meds = set(entities.get("medication_terms") or [])
    include_related_meds = entities.get("section_intent") in _TREATMENT_INTENTS
    matched_meds = _dedupe(
        med
        for entry in matched_entries
        for med in _as_list(entry.get("medicamentos"))
        if include_related_meds or med in explicit_meds
    )
    structured_terms = _build_structured_terms(
        understanding=understanding,
        matched_entries=matched_entries,
        matched_cids=matched_cids,
        cid_descriptions=descriptions,
        matched_meds=matched_meds,
    )
    added_terms = _expanded_query_terms(
        structured_terms=structured_terms,
        original_added_terms=expansion["added_terms"],
        max_terms=max_terms,
    )

    return {
        "original_query": original,
        "expanded_query": _compose_expanded_query(original, added_terms),
        "structured_terms": structured_terms,
        "added_terms": added_terms,
        "source": "catalog_candidates",
        "expansion_reason": expansion["expansion_reason"],
        "intent": understanding.get("intent_result") or {},
        "linked_entities": understanding.get("linked_entities") or [],
        "catalog_candidates": understanding.get("catalog_candidates") or [],
        "matched_diseases": matched_diseases,
        "matched_cid10_codes": matched_cids,
        "matched_medications": matched_meds,
        "matched_terms": added_terms,
        "matched_cid10_descriptions": descriptions,
        "entities": entities,
        "clinical_understanding": understanding,
    }


def _metadata_text(metadata: dict[str, Any]) -> str:
    parts = []
    for key in (
        "source_stem",
        "section",
        "header_1",
        "header_2",
        "disease",
        "disease_normalized",
        "diretriz",
        "cid10_codes",
        "cid10_descriptions",
        "medicamentos",
        "portarias",
    ):
        value = metadata.get(key)
        parts.extend(_as_list(value))
    return normalize_text_for_match(" ".join(parts))


def _document_disease_text(metadata: dict[str, Any]) -> str:
    parts = []
    for key in ("disease", "disease_normalized", "diretriz", "diretriz_normalized", "source_stem"):
        parts.extend(_as_list(metadata.get(key)))
    return normalize_text_for_match(" ".join(parts))


def _doc_disease_normalized(metadata: dict[str, Any]) -> str:
    for key in ("disease_normalized", "disease", "diretriz_normalized", "diretriz"):
        value = metadata.get(key)
        if value:
            return normalize_text_for_match(value)
    return ""


def _document_matches_disease(metadata: dict[str, Any], disease_norm: str) -> bool:
    doc_norm = _doc_disease_normalized(metadata)
    if not doc_norm or not disease_norm:
        return False
    return doc_norm == disease_norm


def _document_has_other_disease(metadata: dict[str, Any]) -> bool:
    return bool(
        metadata.get("disease")
        or metadata.get("disease_normalized")
        or metadata.get("diretriz")
        or metadata.get("diretriz_normalized")
    )


def _removed_doc_record(item: Any, reason: str) -> dict[str, Any]:
    doc, score = _doc_from_pair(item)
    metadata = dict(getattr(doc, "metadata", {}) or {})
    return {
        "source_stem": metadata.get("source_stem"),
        "source_pdf": metadata.get("source_pdf"),
        "diretriz": metadata.get("diretriz"),
        "disease": metadata.get("disease"),
        "section": metadata.get("section") or metadata.get("header_1") or metadata.get("header_2"),
        "dense_score": score,
        "reason": reason,
    }


def _reason_slug(value: Any) -> str:
    return normalize_text_for_match(value).replace(" ", "_")


def _detected_disease_norm(understanding: dict[str, Any]) -> str:
    disease = understanding.get("detected_disease") or {}
    return normalize_text_for_match(disease.get("normalized") or disease.get("name") or "")


def _structured_disease_norm(structured_terms: dict[str, Any] | None, understanding: dict[str, Any]) -> str:
    if structured_terms:
        value = structured_terms.get("disease_normalized") or structured_terms.get("disease") or structured_terms.get("diretriz")
        norm = normalize_text_for_match(value)
        if norm:
            return norm
    return _detected_disease_norm(understanding)


def _query_document_relevance(query_norm: str, text_norm: str, meta_norm: str) -> float:
    if not query_norm:
        return 0.0
    target = f"{meta_norm} {text_norm}".strip()
    if not target:
        return 0.0
    # Use a deterministic lightweight n-gram cosine similarity instead of
    # RapidFuzz here. RapidFuzz use is restricted to catalog matching (see
    # CatalogConceptResolver). This function returns a 0.0-1.0 relevance.
    left = _char_ngram_embedding(query_norm, n=3)
    right = _char_ngram_embedding(target, n=3)
    sim = _cosine_similarity(left, right)
    return min(1.0, max(0.0, float(sim)))


def filter_documents_by_detected_disease(
    documents: list[Any],
    understanding: dict[str, Any],
    *,
    structured_terms: dict[str, Any] | None = None,
    min_confidence: float = 0.84,
) -> tuple[list[Any], dict[str, Any]]:
    """Aplica pós-filtro rígido por disease_normalized quando a doença é confiável."""
    disease = understanding.get("detected_disease") or {}
    disease_norm = _structured_disease_norm(structured_terms, understanding)
    confidence = float((structured_terms or {}).get("confidence") or disease.get("confidence") or 0.0)
    before = len(documents)
    info = {
        "disease_filter_applied": False,
        "filtered_disease": disease_norm,
        "candidate_count_before_filter": before,
        "candidate_count_after_filter": before,
        "disease_filter_fallback": False,
        "has_confident_catalog_candidate": bool(disease_norm and confidence >= min_confidence),
        "documents_removed_by_catalog_filter": [],
    }
    if not disease_norm or confidence < min_confidence:
        return documents, info

    kept = []
    removed = []
    for item in documents:
        doc, _score = _doc_from_pair(item)
        if _document_matches_disease(dict(getattr(doc, "metadata", {}) or {}), disease_norm):
            kept.append(item)
        else:
            removed.append(_removed_doc_record(item, "catalog_candidate_mismatch"))

    info.update(
        {
            "disease_filter_applied": True,
            "candidate_count_after_filter": len(kept),
            "disease_filter_fallback": not bool(kept),
            "documents_removed_by_catalog_filter": removed if kept else [],
        }
    )
    if kept:
        return kept, info
    info["candidate_count_after_filter"] = before
    return documents, info


def _doc_from_pair(item: Any) -> tuple[Document, float | None]:
    if isinstance(item, tuple) and item:
        doc = item[0]
        score = item[1] if len(item) > 1 else None
        return doc, float(score) if score is not None else None
    return item, None


def rerank_documents(
    query: str,
    expanded_query: dict[str, Any],
    documents: list[Any],
    final_k: int = 6,
    *,
    understanding: dict[str, Any] | None = None,
    structured_terms: dict[str, Any] | None = None,
    use_cross_encoder: bool = False,
    cross_encoder_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    cross_encoder_top_n: int = 15,
    min_final_score: float = -5.0,
    require_catalog_match_when_confident: bool = True,
    min_final_score_with_catalog: float = 0.0,
) -> list[Document]:
    """Rerank heurístico explicável sobre candidatos vindos do Chroma."""
    if final_k < 1:
        return []

    clinical_understanding = understanding or expanded_query.get("clinical_understanding") or {}
    structured = structured_terms or expanded_query.get("structured_terms") or {}
    entities = expanded_query.get("entities") or extract_query_entities(query)
    explicit_cids = {
        code.upper()
        for code in (clinical_understanding.get("detected_cid10_codes") or entities.get("cid10_codes") or [])
    }
    catalog_cids = {
        code.upper()
        for code in _as_list(structured.get("cid10_codes") or expanded_query.get("matched_cid10_codes") or [])
        if code.upper() not in explicit_cids
    }
    disease_norm = _structured_disease_norm(structured, clinical_understanding)
    disease_terms = [disease_norm] if disease_norm else []
    explicit_medication_terms = [
        normalize_text_for_match(item.get("name") if isinstance(item, dict) else item)
        for item in (clinical_understanding.get("detected_medications") or entities.get("medication_terms") or [])
    ]
    related_medication_terms = []
    intent = structured.get("intent") or clinical_understanding.get("intent") or entities.get("section_intent")
    if intent in _TREATMENT_INTENTS:
        related_medication_terms = [
            normalize_text_for_match(t)
            for t in _as_list(structured.get("medications") or expanded_query.get("matched_medications") or [])
        ]
    query_norm = normalize_text_for_match(query)
    preferred_sections = _preferred_section_norms(intent, structured)

    candidate_docs, filter_info = filter_documents_by_detected_disease(
        documents,
        clinical_understanding,
        structured_terms=structured,
    )
    has_confident_catalog_candidate = bool(filter_info.get("has_confident_catalog_candidate"))
    expanded_query["_catalog_filter_info"] = filter_info
    total = max(1, len(candidate_docs))
    fallback_wrong_disease = bool(filter_info.get("disease_filter_fallback"))
    ranked: list[tuple[float, Document]] = []
    for idx, item in enumerate(candidate_docs):
        doc, dense_score = _doc_from_pair(item)
        metadata = dict(getattr(doc, "metadata", {}) or {})
        text = str(getattr(doc, "page_content", "") or "")
        text_norm = normalize_text_for_match(text)
        meta_norm = _metadata_text(metadata)
        section_norm = _section_text_norm(metadata)
        source_norm = normalize_text_for_match(metadata.get("source_stem") or "")

        base = 1.0 - (idx / total)
        boost = 0.0
        penalty = 0.0
        reasons: list[str] = []
        disease_match = False
        section_match = False

        meta_cids = {code.upper() for code in _as_list(metadata.get("cid10_codes"))}
        for cid in sorted(explicit_cids):
            if cid in meta_cids:
                boost += 5.0
                reasons.append(f"cid_explicit_match:{cid}")
            if cid and cid.lower() in text.lower():
                boost += 5.0
                reasons.append(f"cid_explicit_text:{cid}")

        for cid in sorted(catalog_cids):
            if cid in meta_cids:
                reasons.append(f"cid_catalog_hint_ignored:{cid}")

        for disease in disease_terms:
            if disease and _document_matches_disease(metadata, disease):
                boost += 10.0 if has_confident_catalog_candidate else 5.0
                disease_match = True
                reasons.append("catalog_candidate_match")
                reasons.append(f"disease_exact_match:{_reason_slug(disease)}")
                if filter_info.get("disease_filter_applied") and not filter_info.get("disease_filter_fallback"):
                    reasons.append(f"filtered_by_detected_disease:{_reason_slug(disease)}")
                break

        # If the query indicates a specific disease but this document is from
        # another disease, penalize lightly — but do not dominate ranking with
        # hard cutoffs. Heavier filtering should be done by
        # `filter_documents_by_detected_disease` when confidence is high.
        if disease_terms and _document_has_other_disease(metadata) and not disease_match:
            penalty += 2.0 if fallback_wrong_disease else 1.0
            doc_disease = metadata.get("disease") or metadata.get("diretriz") or metadata.get("source_stem") or "unknown"
            reasons.append("catalog_candidate_mismatch")
            reasons.append(f"penalty_wrong_disease:{_reason_slug(doc_disease)}")
            reasons.append(f"penalty_other_disease:{_reason_slug(doc_disease)}")

        for med in explicit_medication_terms:
            if med and med in meta_norm:
                boost += 5.0
                reasons.append(f"medication_explicit_match:{_reason_slug(med)}")
            if med and med in text_norm:
                boost += 5.0
                reasons.append(f"medication_explicit_text:{_reason_slug(med)}")

        for med in related_medication_terms:
            if med and med in meta_norm:
                if intent == "criterios_inclusao":
                    reasons.append(f"medication_related_hint_ignored:{_reason_slug(med)}")
                else:
                    boost += 0.5
                    reasons.append(f"medication_related_hint:{_reason_slug(med)}")

        # Section signals are kept much weaker than catalog matches. They are
        # derived from canonical section labels, not from clinical term lists.
        section_targets = preferred_sections
        section_hit = any(section and section in section_norm for section in section_targets)
        if intent and disease_terms and not disease_match and _document_has_other_disease(metadata):
            if section_hit:
                reasons.append("section_match_ignored_without_catalog_match")
        elif section_hit:
            if not has_confident_catalog_candidate and not disease_match:
                boost += 0.2
                section_match = True
                reasons.append(f"section_intent_match_weak:{intent}")
            elif intent == "criterios_inclusao":
                boost += 8.0 if disease_match and has_confident_catalog_candidate else 1.0
            elif intent == "criterios_exclusao":
                boost += 8.0 if disease_match and has_confident_catalog_candidate else 1.0
            elif intent == "tratamento":
                boost += 8.0 if disease_match and has_confident_catalog_candidate else 0.8
            else:
                boost += 6.0 if disease_match and has_confident_catalog_candidate else 0.8
            if not section_match:
                section_match = True
                reasons.append(f"section_intent_match:{intent}")

        # Combined disease+section signals provide a small additional signal
        # but should not overwhelm semantic relevance.
        if disease_match and section_match:
            boost += 1.0
            reasons.append("combined_disease_section_match")

        if section_targets and section_norm and not section_hit and disease_match:
            other_section = next((label for label in _INTENT_SECTION_NORMS.values() if label in section_norm), "")
            if other_section:
                penalty += 4.0 if has_confident_catalog_candidate else 0.8
                reasons.append(f"penalty_wrong_section:{_reason_slug(other_section)}")
            elif has_confident_catalog_candidate:
                penalty += 1.0
                reasons.append("penalty_section_not_preferred")

        query_relevance = _query_document_relevance(query_norm, text_norm, meta_norm)
        if query_relevance >= 0.65:
            boost += query_relevance
            reasons.append(f"query_text_relevance:{query_relevance:.2f}")

        if intent not in {"regulatorio", "regulacao"}:
            for admin_term, admin_penalty in ADMIN_SECTION_PENALTIES.items():
                if admin_term in section_norm:
                    penalty += abs(admin_penalty)
                    reasons.append(f"penalty_wrong_section:{_reason_slug(admin_term)}")
                    break

        section_penalties = SECTION_PENALTIES_BY_INTENT.get(str(intent), {})
        wrong_section = next((term for term in section_penalties if term in section_norm), "")
        if wrong_section:
            penalty += abs(section_penalties[wrong_section])
            reasons.append(f"penalty_wrong_section:{_reason_slug(wrong_section)}")

        final_score = base + boost - penalty
        metadata.update(
            {
                "dense_score": dense_score,
                "dense_rank": idx + 1,
                "dense_rank_score": round(base, 6),
                "heuristic_score": round(final_score, 6),
                "disease_filter_applied": filter_info.get("disease_filter_applied", False),
                "filtered_disease": filter_info.get("filtered_disease") or "",
                "candidate_count_before_filter": filter_info.get("candidate_count_before_filter"),
                "candidate_count_after_filter": filter_info.get("candidate_count_after_filter"),
                "disease_filter_fallback": filter_info.get("disease_filter_fallback", False),
                "has_confident_catalog_candidate": has_confident_catalog_candidate,
                "catalog_filter_fallback": filter_info.get("disease_filter_fallback", False),
                "cross_encoder_score": None,
                "final_score": round(final_score, 6),
                "ranking_reasons": reasons,
            }
        )
        ranked_doc = Document(page_content=text, metadata=metadata, id=getattr(doc, "id", None))
        ranked.append((final_score, ranked_doc))

    ranked.sort(key=lambda item: item[0], reverse=True)
    if has_confident_catalog_candidate and require_catalog_match_when_confident and not filter_info.get("disease_filter_fallback"):
        threshold = float(min_final_score_with_catalog)
        heuristic_docs = [
            doc
            for score, doc in ranked
            if score >= threshold and "catalog_candidate_match" in _as_list(doc.metadata.get("ranking_reasons"))
        ]
    else:
        heuristic_docs = [doc for score, doc in ranked if score >= float(min_final_score)]

    expanded_query["_catalog_filter_info"] = {
        **filter_info,
        "documents_after_final_filter": len(heuristic_docs),
        "final_documents_count": min(len(heuristic_docs), final_k),
        "returned_less_than_final_k": len(heuristic_docs[:final_k]) < final_k,
    }
    if use_cross_encoder:
        heuristic_docs = apply_cross_encoder_rerank(
            query,
            heuristic_docs,
            model_name=cross_encoder_model_name,
            top_n=cross_encoder_top_n,
        )
    return heuristic_docs[:final_k]


def _format_list(value: Any, *, max_items: int = 10, max_chars: int = 500) -> str:
    items = _as_list(value)
    if not items:
        return "-"
    shown = items[:max_items]
    text = "; ".join(shown)
    if len(items) > max_items:
        text += "; ..."
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def format_context_document(doc: Document, rank: int) -> str:
    """Formata um documento recuperado com metadados ricos para o prompt."""
    meta = dict(doc.metadata or {})
    page_start = meta.get("page_start", "?")
    page_end = meta.get("page_end", "?")
    reasons = _format_list(meta.get("ranking_reasons"), max_items=8, max_chars=240)
    return (
        f"[Documento {rank}]\n"
        f"Diretriz: {meta.get('diretriz') or '-'}\n"
        f"Doença: {meta.get('disease') or '-'}\n"
        f"CID-10: {_format_list(meta.get('cid10_codes'), max_items=12, max_chars=240)}\n"
        f"Medicamentos relacionados: {_format_list(meta.get('medicamentos'), max_items=10, max_chars=600)}\n"
        f"Seção: {meta.get('section') or meta.get('header_1') or '-'}\n"
        f"Fonte: {meta.get('source_pdf') or meta.get('source_stem') or '-'}\n"
        f"Páginas: {page_start}-{page_end}\n"
        f"Score final: {meta.get('final_score', '-')}\n"
        f"Motivos do ranking: {reasons}\n\n"
        f"Trecho:\n{str(doc.page_content or '').strip()}"
    )


def format_rich_context_block(docs: list[Document]) -> str:
    return "\n\n---\n\n".join(format_context_document(doc, i) for i, doc in enumerate(docs, start=1))


def document_audit_record(doc: Document, rank: int) -> dict[str, Any]:
    meta = dict(doc.metadata or {})
    return {
        "rank": rank,
        "source_stem": meta.get("source_stem"),
        "source_pdf": meta.get("source_pdf"),
        "diretriz": meta.get("diretriz"),
        "disease": meta.get("disease"),
        "section": meta.get("section"),
        "page_start": meta.get("page_start"),
        "page_end": meta.get("page_end"),
        "page_range": _as_list(meta.get("page_range")) or meta.get("page_range"),
        "cid10_codes": _as_list(meta.get("cid10_codes")),
        "medicamentos": _as_list(meta.get("medicamentos")),
        "portarias": _as_list(meta.get("portarias")),
        "dense_score": meta.get("dense_score"),
        "dense_rank_score": meta.get("dense_rank_score"),
        "heuristic_score": meta.get("heuristic_score"),
        "cross_encoder_score": meta.get("cross_encoder_score"),
        "final_score": meta.get("final_score"),
        "ranking_reasons": _as_list(meta.get("ranking_reasons")),
    }


def build_audit_payload(
    *,
    question: str,
    expansion: dict[str, Any],
    documents: list[Document],
    retrieval_candidates_k: int,
    retrieval_final_k: int,
    answer: str = "",
    audit_id: str | None = None,
) -> dict[str, Any]:
    first_meta = dict(documents[0].metadata or {}) if documents else {}
    filter_info = expansion.get("_catalog_filter_info") or {}
    complementary_info = expansion.get("_complementary_retrieve_info") or {}
    structured_terms = expansion.get("structured_terms") or {}
    catalog_candidates = (structured_terms.get("catalog_candidates") or (expansion.get("clinical_understanding") or {}).get("catalog_candidates") or [])
    has_confident_catalog_candidate = bool(filter_info.get("has_confident_catalog_candidate", False))
    return {
        "audit_id": audit_id or str(uuid.uuid4()),
        "question": question,
        "original_query": expansion.get("original_query") or question,
        "clinical_understanding": expansion.get("clinical_understanding") or {},
        "intent": (expansion.get("clinical_understanding") or {}).get("intent_result") or {},
        "linked_entities": (expansion.get("clinical_understanding") or {}).get("linked_entities") or [],
        "catalog_candidates": catalog_candidates,
        "expanded_query": expansion.get("expanded_query") or question,
        "structured_terms": structured_terms,
        "added_terms": expansion.get("added_terms") or expansion.get("matched_terms") or [],
        "expansion_reason": expansion.get("expansion_reason") or [],
        "matched_diseases": expansion.get("matched_diseases") or [],
        "matched_cid10_codes": expansion.get("matched_cid10_codes") or [],
        "matched_medications": expansion.get("matched_medications") or [],
        "matched_terms": expansion.get("matched_terms") or [],
        "retrieval_candidates_k": retrieval_candidates_k,
        "retrieval_final_k": retrieval_final_k,
        "has_confident_catalog_candidate": has_confident_catalog_candidate,
        "catalog_candidate_missing": not bool(catalog_candidates),
        "low_confidence_retrieval": not has_confident_catalog_candidate,
        "disease_filter_applied": bool(first_meta.get("disease_filter_applied", False)),
        "filtered_disease": first_meta.get("filtered_disease") or "",
        "candidate_count_before_filter": filter_info.get("candidate_count_before_filter", first_meta.get("candidate_count_before_filter")),
        "candidate_count_after_filter": filter_info.get("candidate_count_after_filter", first_meta.get("candidate_count_after_filter")),
        "candidate_count_before_rerank": retrieval_candidates_k,
        "documents_before_filter": filter_info.get("candidate_count_before_filter", retrieval_candidates_k),
        "documents_after_catalog_filter": filter_info.get("candidate_count_after_filter", first_meta.get("candidate_count_after_filter")),
        "documents_removed_by_catalog_filter": filter_info.get("documents_removed_by_catalog_filter") or [],
        "catalog_filter_fallback": bool(filter_info.get("disease_filter_fallback", False)),
        "complementary_retrieve": complementary_info,
        "complementary_retrieve_used": bool(complementary_info.get("used", False)),
        "complementary_query": complementary_info.get("query") or "",
        "preferred_section_found": bool(
            complementary_info.get("preferred_section_found", filter_info.get("preferred_section_found", False))
        ),
        "preferred_section_not_found": bool(
            complementary_info.get("preferred_section_not_found", filter_info.get("preferred_section_not_found", False))
        ),
        "candidate_count_after_catalog_filter": filter_info.get("candidate_count_after_filter", first_meta.get("candidate_count_after_filter")),
        "final_documents_count": len(documents),
        "returned_less_than_final_k": len(documents) < retrieval_final_k,
        "final_documents": [document_audit_record(doc, i) for i, doc in enumerate(documents, start=1)],
        "use_cross_encoder": bool(expansion.get("use_cross_encoder", False)),
        "cross_encoder_model": expansion.get("cross_encoder_model"),
        "documents": [document_audit_record(doc, i) for i, doc in enumerate(documents, start=1)],
        "answer": answer,
        "created_at": datetime.now(UTC).isoformat(),
    }


def append_audit_jsonl(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_json_safe(payload), ensure_ascii=False, sort_keys=True) + "\n")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Document):
        return {
            "page_content_preview": str(value.page_content or "")[:800],
            "metadata": _json_safe(dict(value.metadata or {})),
        }
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return [_json_safe(item) for item in sorted(value, key=str)]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
