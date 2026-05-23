"""Nó de recuperação: similaridade no Chroma PCDT."""

from __future__ import annotations

import time

from langchain_chroma import Chroma
from langchain_core.documents import Document

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.rag_enhancement import format_rich_context_block
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate
from assistente_medico_api.services.rag_retrieval_service import (
    format_source_label,
    run_rag_retrieval,
)


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
    result = run_rag_retrieval(
        query,
        store,
        settings,
        existing_reasoning_steps=list(state.get("reasoning_steps") or []),
    )

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    stems_list = sorted({d.metadata.get("source_stem", "?") for d in result.retrieved_docs}) if result.retrieved_docs else []
    audit(
        "rag_retrieve_done",
        kind="rag",
        latency_ms=latency_ms,
        patient_id=pid,
        retrieval_query_snippet=truncate(query),
        expanded_query_snippet=truncate(result.expanded_query),
        structured_terms=result.structured_terms,
        catalog_candidates=result.catalog_candidates,
        retrieved_count=len(result.retrieved_docs),
        source_stems=stems_list,
        documents_before_filter=result.audit_payload.get("documents_before_filter"),
        documents_after_filter=result.audit_payload.get("documents_after_catalog_filter"),
        complementary_retrieve_info=result.audit_payload.get("complementary_retrieve"),
        final_documents=result.audit_payload.get("final_documents"),
        top_k=result.audit_payload.get("retrieval_final_k"),
    )

    return {
        "retrieval_query": result.expanded_query,
        "retrieved_docs": result.retrieved_docs,
        "sources": result.sources,
        "reasoning_steps": result.reasoning_steps,
        "query_expansion": result.query_expansion,
        "clinical_understanding": result.clinical_understanding,
        "rag_audit_payload": result.audit_payload,
    }
