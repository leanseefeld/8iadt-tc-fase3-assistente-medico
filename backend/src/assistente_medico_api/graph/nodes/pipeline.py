"""Pipeline nodes with single-purpose responsibilities for chat RAG."""

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
    route_context_quality,
    run_load_memory,
    run_rerank_and_validate_context,
    run_retrieve,
    run_save_memory,
    run_search_router,
)


def load_memory_node(state: ChatRAGState) -> dict:
    out = run_load_memory(dict(state))
    audit("rag_memory_loaded", kind="rag", memory_result=out.get("memory_result") or {})
    return out


def router_search_needed_node(state: ChatRAGState, *, settings: Settings | None = None) -> dict:
    out = run_search_router(state.get("query") or "", state.get("memory_result") or state.get("memory_context"), settings)
    audit("rag_search_router_done", kind="rag", router_result=out.get("router_result") or {})
    audit_trace = append_audit_step(
        {**dict(state), **out},
        node="router_search_needed",
        input_summary={"query": state.get("query") or ""},
        output_summary=out.get("router_result") or {},
        settings=settings,
    )
    return {
        **out,
        "max_retrieve_attempts": int(state.get("max_retrieve_attempts") or 2),
        "audit_trace": audit_trace,
        "rag_audit_payload": build_pipeline_audit({**dict(state), **out, "audit_trace": audit_trace}),
    }


def route_search_needed(state: ChatRAGState) -> str:
    return "rag" if state.get("search_needed") else "direct"


def retrieve_attempt_1_node(state: ChatRAGState, *, store: Chroma, settings: Settings) -> dict:
    out = run_retrieve(
        expanded_query=state.get("expanded_query") or state.get("retrieval_query") or state.get("query") or "",
        structured_terms=state.get("structured_terms") or {},
        store=store,
        settings=settings,
        retrieve_attempt=1,
    )
    merged = {**dict(state), **out}
    audit_trace = append_audit_step(
        merged,
        node=f"retrieve_attempt_{out.get('retrieve_attempt') or 1}",
        input_summary={"expanded_query": state.get("expanded_query") or state.get("retrieval_query") or ""},
        output_summary=out.get("retrieve_result") or {},
        settings=settings,
    )
    audit("rag_retrieve_attempt_done", kind="rag", retrieve_debug=out.get("retrieve_debug") or {})
    return {
        **out,
        "audit_trace": audit_trace,
        "rag_audit_payload": build_pipeline_audit({**merged, "audit_trace": audit_trace}),
    }


async def rerank_and_validate_context_node(state: ChatRAGState, *, settings: Settings) -> dict:
    out = await run_rerank_and_validate_context(
        query=state.get("query") or "",
        expanded_query=state.get("expanded_query") or state.get("retrieval_query") or "",
        structured_terms=state.get("structured_terms") or {},
        clinical_understanding=state.get("clinical_understanding") or {},
        candidate_docs=state.get("candidate_docs") or [],
        settings=settings,
    )
    merged = {**dict(state), **out}
    audit_trace = append_audit_step(
        merged,
        node="rerank_and_validate_context",
        output_summary={
            "context_quality": (out.get("rerank_result") or {}).get("context_quality"),
            "failure_type": (out.get("rerank_result") or {}).get("failure_type"),
            "selected_count": len(out.get("retrieved_docs") or []),
        },
        settings=settings,
    )
    audit(
        "rag_rerank_validate_done",
        kind="rag",
        context_sufficient=out.get("context_sufficient"),
        insufficiency_reason=out.get("insufficiency_reason"),
        rerank_debug=out.get("rerank_debug") or {},
    )
    return {
        **out,
        "audit_trace": audit_trace,
        "rag_audit_payload": build_pipeline_audit({**merged, "audit_trace": audit_trace}),
    }


def context_quality_router(state: ChatRAGState) -> str:
    return route_context_quality(dict(state))


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


def save_memory_node(state: ChatRAGState, *, settings: Settings | None = None) -> dict:
    out = run_save_memory(dict(state), settings=settings)
    audit("rag_memory_saved", kind="rag", memory_saved=out.get("memory_saved"), conversation_id=state.get("conversation_id"))
    return {
        **out,
        "rag_audit_payload": build_pipeline_audit({**dict(state), **out}),
    }
