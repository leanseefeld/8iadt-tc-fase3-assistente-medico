"""Retrieve node: fetch raw Chroma candidates only."""

from __future__ import annotations

import time

from langchain_chroma import Chroma

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.context_formatting import format_context_block
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate
from assistente_medico_api.services.rag_pipeline_service import (
    build_pipeline_audit,
    format_source_label,
    run_retrieve,
)


def retrieve_node(
    state: ChatRAGState,
    *,
    store: Chroma,
    settings: Settings,
) -> dict:
    """Retrieve raw candidate_docs. Final selection belongs to rerank node."""
    t0 = time.perf_counter()
    out = run_retrieve(
        expanded_query=state.get("expanded_query") or state.get("retrieval_query") or state.get("query") or "",
        structured_terms=state.get("structured_terms") or {},
        store=store,
        settings=settings,
        retrieve_attempt=int(state.get("retrieve_attempt") or 1),
    )
    steps = list(state.get("reasoning_steps") or [])
    debug = out.get("retrieve_debug") or {}
    steps.append(
        "Retrieve: buscou candidatos no Chroma "
        f"(attempt={out.get('retrieve_attempt')}, k={debug.get('k')}, candidatos={debug.get('candidate_count')})."
    )
    merged = {**dict(state), **out, "reasoning_steps": steps}
    audit(
        "rag_retrieve_attempt_done",
        kind="rag",
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        patient_id=state.get("patient_id") or None,
        expanded_query_snippet=truncate(debug.get("query_sent_to_chroma") or ""),
        retrieve_attempt=out.get("retrieve_attempt"),
        candidate_count=debug.get("candidate_count"),
        metadata_filter=debug.get("metadata_filter"),
    )
    return {
        **out,
        "reasoning_steps": steps,
        "rag_audit_payload": build_pipeline_audit(merged),
    }


def retrieve_attempt_1_node(state: ChatRAGState, *, store: Chroma, settings: Settings) -> dict:
    return retrieve_node({**dict(state), "retrieve_attempt": 1}, store=store, settings=settings)
