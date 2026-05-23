"""Nó de recuperação: similaridade no Chroma PCDT."""

from __future__ import annotations

from functools import lru_cache
import logging

import time

from langchain_chroma import Chroma
from langchain_core.documents import Document

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate
from assistente_medico_api.graph.rag_enhancement import (
    apply_complementary_retrieve_info,
    build_complementary_retrieve_plan,
    build_audit_payload,
    expand_query_with_conitec_catalog,
    format_rich_context_block,
    load_local_conitec_catalog,
    merge_retrieval_pairs,
    rerank_documents,
)

_logger = logging.getLogger("assistente_medico.rag")


@lru_cache(maxsize=1)
def _cached_conitec_catalog() -> dict:
    return load_local_conitec_catalog()


def format_source_label(doc: Document, index: int) -> str:
    """Rótulo amigável para a UI; ``index`` alinha ao rank do prompt de geração."""
    meta = doc.metadata
    diretriz = meta.get("diretriz") or meta.get("disease") or meta.get("source_stem", "?")
    section = meta.get("section")
    p0 = meta.get("page_start", "?")
    p1 = meta.get("page_end", "?")
    if section:
        body = f"PCDT {diretriz} — {section} (pp. {p0}-{p1})"
    else:
        body = f"PCDT {diretriz} (pp. {p0}-{p1})"
    return f"[{index}] {body}"


def format_context_block(docs: list[Document]) -> str:
    """Monta bloco de contexto para o prompt."""
    return format_rich_context_block(docs)


def retrieve_node(
    state: ChatRAGState,
    *,
    store: Chroma,
    settings: Settings,
) -> dict:
    """
    Executa busca por similaridade usando retrieval_query (reescrita) quando existir.

    Síncrono para poder ser executado em asyncio.to_thread no endpoint.
    """
    pid = state.get("patient_id") or None
    t0 = time.perf_counter()
    query = (state.get("retrieval_query") or state.get("query") or "").strip()
    candidates_k = max(1, int(getattr(settings, "rag_retrieve_candidates_k", 30)))
    final_k = max(1, int(getattr(settings, "rag_retrieve_final_k", settings.retrieval_k)))

    catalog = _cached_conitec_catalog()
    try:
        expansion = expand_query_with_conitec_catalog(query, catalog, max_terms=10)
    except Exception as exc:
        _logger.warning("Falha na expansão da query; usando consulta original. erro=%s", exc)
        expansion = {
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
        }

    retrieval_query = (expansion.get("expanded_query") or query).strip()
    expansion["use_cross_encoder"] = bool(getattr(settings, "rag_use_cross_encoder_rerank", False))
    expansion["cross_encoder_model"] = (
        str(getattr(settings, "rag_cross_encoder_model", "cross-encoder/ms-marco-MiniLM-L-6-v2"))
        if expansion["use_cross_encoder"]
        else None
    )
    pairs = store.similarity_search_with_score(retrieval_query, k=candidates_k)
    complement_pairs = []
    try:
        complement_plan = build_complementary_retrieve_plan(
            query=query,
            expansion=expansion,
            documents=pairs,
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
                _logger.debug("Falha na busca complementar com filtro; tentando sem filtro. erro=%s", exc)
                complement_pairs = store.similarity_search_with_score(complement_query, k=candidates_k)
        pairs = merge_retrieval_pairs(pairs, complement_pairs)
        apply_complementary_retrieve_info(
            expansion,
            plan=complement_plan,
            complementary_pairs=complement_pairs,
            merged_pairs=pairs,
        )
    except Exception as exc:
        _logger.warning("Falha na busca complementar; seguindo com candidatos iniciais. erro=%s", exc)
    try:
        docs = rerank_documents(
            query=query,
            expanded_query=expansion,
            documents=pairs,
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
    except Exception as exc:
        _logger.warning("Falha no reranking; usando ordem densa original. erro=%s", exc)
        docs = []
        for rank, (doc, score) in enumerate(pairs[:final_k], start=1):
            meta = dict(doc.metadata or {})
            meta.update(
                {
                    "dense_score": float(score) if score is not None else None,
                    "dense_rank": rank,
                    "dense_rank_score": round(1.0 - ((rank - 1) / max(1, len(pairs))), 6),
                    "heuristic_score": 0.0,
                    "final_score": round(1.0 - ((rank - 1) / max(1, len(pairs))), 6),
                    "ranking_reasons": ["fallback:dense_order"],
                }
            )
            docs.append(Document(page_content=doc.page_content, metadata=meta, id=getattr(doc, "id", None)))

    sources = [format_source_label(d, i) for i, d in enumerate(docs, start=1)]
    reasoning_steps = list(state.get("reasoning_steps") or [])
    reasoning_steps.append(
        "Consultou a base PCDT com "
        f"k_inicial={candidates_k}, k_final={final_k} "
        f"(consulta expandida: {retrieval_query[:120]}{'…' if len(retrieval_query) > 120 else ''})."
    )
    if expansion.get("matched_terms"):
        reasoning_steps.append(
            "Expansão Conitec: "
            + ", ".join(str(term) for term in expansion.get("matched_terms", [])[:8])
            + ("..." if len(expansion.get("matched_terms", [])) > 8 else "")
        )
    if docs:
        stems = sorted({d.metadata.get("source_stem", "?") for d in docs})
        reasoning_steps.append(f"Fragmentos de: {', '.join(stems)}.")
    else:
        reasoning_steps.append("Nenhum fragmento acima do limiar retornado.")

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    stems_list = sorted({d.metadata.get("source_stem", "?") for d in docs}) if docs else []
    audit(
        "rag_retrieve_done",
        kind="rag",
        latency_ms=latency_ms,
        patient_id=pid,
        retrieval_query_snippet=truncate(query),
        retrieved_count=len(docs),
        source_stems=stems_list,
        top_k=final_k,
    )

    return {
        "retrieved_docs": docs,
        "sources": sources,
        "reasoning_steps": reasoning_steps,
        "query_expansion": expansion,
        "clinical_understanding": expansion.get("clinical_understanding") or {},
        "rag_audit_payload": build_audit_payload(
            question=state.get("query") or "",
            expansion=expansion,
            documents=docs,
            retrieval_candidates_k=candidates_k,
            retrieval_final_k=final_k,
        ),
    }
