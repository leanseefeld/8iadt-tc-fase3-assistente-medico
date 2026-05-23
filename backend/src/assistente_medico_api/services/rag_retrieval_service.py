"""Single catalog-aware RAG retrieval pipeline used by chat and inspector."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.rag_enhancement import (
    apply_complementary_retrieve_info,
    build_audit_payload,
    build_complementary_retrieve_plan,
    document_audit_record,
    expand_query_with_conitec_catalog,
    load_local_conitec_catalog,
    merge_retrieval_pairs,
    rerank_documents,
)

_logger = logging.getLogger("assistente_medico.rag")


@dataclass(frozen=True)
class RagRetrievalResult:
    original_query: str
    expanded_query: str
    structured_terms: dict[str, Any]
    clinical_understanding: dict[str, Any]
    catalog_candidates: list[Any]
    retrieved_docs: list[Document]
    sources: list[str]
    reasoning_steps: list[str]
    audit_payload: dict[str, Any]
    query_expansion: dict[str, Any]
    debug: dict[str, Any]


@lru_cache(maxsize=1)
def cached_conitec_catalog() -> dict:
    return load_local_conitec_catalog()


def format_source_label(doc: Document, index: int | None = None) -> str:
    """Human-readable source label aligned with prompt document ranks."""
    meta = doc.metadata
    diretriz = meta.get("diretriz") or meta.get("disease") or meta.get("source_stem", "?")
    section = meta.get("section")
    p0 = meta.get("page_start", "?")
    p1 = meta.get("page_end", "?")
    if section:
        body = f"PCDT {diretriz} - {section} (pp. {p0}-{p1})"
    else:
        body = f"PCDT {diretriz} (pp. {p0}-{p1})"
    return f"[{index}] {body}" if index is not None else body


def _empty_expansion(query: str) -> dict[str, Any]:
    return {
        "original_query": query,
        "expanded_query": query,
        "structured_terms": {
            "disease": None,
            "disease_normalized": None,
            "diretriz": None,
            "cid10_codes": [],
            "cid10_descriptions": [],
            "medications": [],
            "intent": None,
            "preferred_sections": [],
            "catalog_candidates": [],
            "linked_entities": [],
            "confidence": 0.0,
        },
        "source": "catalog_candidates",
        "matched_diseases": [],
        "matched_cid10_codes": [],
        "matched_medications": [],
        "matched_terms": [],
        "entities": {},
        "clinical_understanding": {},
        "_catalog_filter_info": {},
        "_complementary_retrieve_info": {},
    }


def _pair_records(pairs: list[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for rank, item in enumerate(pairs, start=1):
        doc = item[0] if isinstance(item, tuple) else item
        score = item[1] if isinstance(item, tuple) and len(item) > 1 else None
        meta = dict(getattr(doc, "metadata", {}) or {})
        records.append(
            {
                "rank": rank,
                "score": float(score) if score is not None else None,
                "source_stem": meta.get("source_stem"),
                "diretriz": meta.get("diretriz"),
                "disease": meta.get("disease"),
                "section": meta.get("section") or meta.get("header_1") or meta.get("header_2"),
                "page_start": meta.get("page_start"),
                "page_end": meta.get("page_end"),
            }
        )
    return records


def run_rag_retrieval(
    query: str,
    store: Chroma,
    settings: Settings,
    *,
    existing_reasoning_steps: list[str] | None = None,
) -> RagRetrievalResult:
    """Run the same retrieval, filtering and reranking pipeline for every caller."""
    original_query = (query or "").strip()
    candidates_k = max(1, int(getattr(settings, "rag_retrieve_candidates_k", 30)))
    final_k = max(1, int(getattr(settings, "rag_retrieve_final_k", settings.retrieval_k)))

    catalog = cached_conitec_catalog()
    try:
        expansion = expand_query_with_conitec_catalog(original_query, catalog, max_terms=10)
    except Exception as exc:
        _logger.warning("rag_query_expansion_failed; using original query. error=%s", exc)
        expansion = _empty_expansion(original_query)

    retrieval_query = str(expansion.get("expanded_query") or original_query).strip()
    expansion["use_cross_encoder"] = bool(getattr(settings, "rag_use_cross_encoder_rerank", False))
    expansion["cross_encoder_model"] = (
        str(getattr(settings, "rag_cross_encoder_model", "cross-encoder/ms-marco-MiniLM-L-6-v2"))
        if expansion["use_cross_encoder"]
        else None
    )

    primary_pairs = store.similarity_search_with_score(retrieval_query, k=candidates_k)
    complement_pairs: list[Any] = []
    merged_pairs = list(primary_pairs)
    complement_plan: dict[str, Any] = {}
    try:
        complement_plan = build_complementary_retrieve_plan(
            query=original_query,
            expansion=expansion,
            documents=primary_pairs,
            final_k=final_k,
        )
        if complement_plan.get("should_run"):
            complement_query = str(complement_plan.get("query") or "").strip()
            metadata_filter = complement_plan.get("metadata_filter")
            try:
                complement_pairs = store.similarity_search_with_score(
                    complement_query,
                    k=candidates_k,
                    filter=metadata_filter,
                )
            except TypeError:
                complement_pairs = store.similarity_search_with_score(complement_query, k=candidates_k)
            except Exception as exc:
                _logger.debug("rag_complementary_filtered_search_failed; retrying without filter. error=%s", exc)
                complement_pairs = store.similarity_search_with_score(complement_query, k=candidates_k)
        merged_pairs = merge_retrieval_pairs(primary_pairs, complement_pairs)
        apply_complementary_retrieve_info(
            expansion,
            plan=complement_plan,
            complementary_pairs=complement_pairs,
            merged_pairs=merged_pairs,
        )
    except Exception as exc:
        _logger.warning("rag_complementary_retrieve_failed; using primary candidates. error=%s", exc)

    docs = rerank_documents(
        query=original_query,
        expanded_query=expansion,
        documents=merged_pairs,
        final_k=final_k,
        understanding=expansion.get("clinical_understanding") or {},
        structured_terms=expansion.get("structured_terms") or {},
        use_cross_encoder=bool(getattr(settings, "rag_use_cross_encoder_rerank", False)),
        cross_encoder_model_name=str(getattr(settings, "rag_cross_encoder_model", "cross-encoder/ms-marco-MiniLM-L-6-v2")),
        cross_encoder_top_n=int(getattr(settings, "rag_cross_encoder_top_n", 15)),
        min_final_score=float(getattr(settings, "rag_min_final_score", -5.0)),
        require_catalog_match_when_confident=bool(getattr(settings, "rag_require_catalog_match_when_confident", True)),
        min_final_score_with_catalog=float(getattr(settings, "rag_min_final_score_with_catalog", 0.0)),
    )

    sources = [format_source_label(doc, index) for index, doc in enumerate(docs, start=1)]
    reasoning_steps = list(existing_reasoning_steps or [])
    reasoning_steps.append(
        "Consultou a base PCDT com "
        f"k_inicial={candidates_k}, k_final={final_k} "
        f"(consulta expandida: {retrieval_query[:120]}{'...' if len(retrieval_query) > 120 else ''})."
    )
    if expansion.get("matched_terms"):
        terms = [str(term) for term in expansion.get("matched_terms", [])[:8]]
        reasoning_steps.append(
            "Expansão Conitec: "
            + ", ".join(terms)
            + ("..." if len(expansion.get("matched_terms", [])) > 8 else "")
        )
    if docs:
        stems = sorted({doc.metadata.get("source_stem", "?") for doc in docs})
        reasoning_steps.append(f"Fragmentos de: {', '.join(stems)}.")
    else:
        reasoning_steps.append("Nenhum fragmento compatível foi retornado após filtro/rerank.")

    audit_payload = build_audit_payload(
        question=original_query,
        expansion=expansion,
        documents=docs,
        retrieval_candidates_k=candidates_k,
        retrieval_final_k=final_k,
    )
    structured_terms = expansion.get("structured_terms") or {}
    clinical_understanding = expansion.get("clinical_understanding") or {}
    catalog_candidates = structured_terms.get("catalog_candidates") or clinical_understanding.get("catalog_candidates") or []
    debug = {
        "retrieval_query": retrieval_query,
        "primary_candidates": _pair_records(list(primary_pairs)),
        "complementary_plan": complement_plan,
        "complementary_candidates": _pair_records(complement_pairs),
        "merged_candidates_count": len(merged_pairs),
        "final_documents": [document_audit_record(doc, i) for i, doc in enumerate(docs, start=1)],
    }
    return RagRetrievalResult(
        original_query=original_query,
        expanded_query=retrieval_query,
        structured_terms=structured_terms,
        clinical_understanding=clinical_understanding,
        catalog_candidates=list(catalog_candidates),
        retrieved_docs=docs,
        sources=sources,
        reasoning_steps=reasoning_steps,
        audit_payload=audit_payload,
        query_expansion=expansion,
        debug=debug,
    )
