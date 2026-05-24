"""LangGraph node: run the single allowed fallback retrieve attempt."""

from __future__ import annotations

from langchain_chroma import Chroma

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit
from assistente_medico_api.services.rag_pipeline_service import (
    append_audit_step,
    build_fallback_query,
    build_pipeline_audit,
    merge_candidate_attempts,
    run_retrieve,
)


def fallback_retrieve_node(state: ChatRAGState, *, store: Chroma, settings: Settings) -> dict:
    attempt = min(2, int(state.get("retrieve_attempt") or 1) + 1)
    fallback_query = build_fallback_query(state.get("query") or "", state.get("structured_terms") or {})
    out = run_retrieve(
        expanded_query=state.get("expanded_query") or state.get("retrieval_query") or state.get("query") or "",
        structured_terms=state.get("structured_terms") or {},
        store=store,
        settings=settings,
        retrieve_attempt=attempt,
        fallback_query=fallback_query,
    )
    previous = list(state.get("candidate_docs") or [])
    current = list(out.get("candidate_docs") or [])
    merged_candidates = merge_candidate_attempts(previous, current)
    out["candidate_docs_attempt_1"] = previous
    out["candidate_docs_attempt_2"] = current
    out["candidate_docs_combined"] = merged_candidates
    out["candidate_docs"] = merged_candidates
    merged = {**dict(state), **out}
    audit_trace = append_audit_step(
        merged,
        node="fallback_retrieve_attempt_2",
        input_summary={"reason": state.get("insufficiency_reason")},
        output_summary=out.get("retrieve_result") or {},
        settings=settings,
    )
    audit("rag_fallback_retrieve_done", kind="rag", retrieve_debug=out.get("retrieve_debug") or {})
    return {
        **out,
        "audit_trace": audit_trace,
        "rag_audit_payload": build_pipeline_audit({**merged, "audit_trace": audit_trace}),
    }
