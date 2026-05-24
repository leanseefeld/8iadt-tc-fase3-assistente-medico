"""Pipeline nodes with single-purpose responsibilities for chat RAG."""

from __future__ import annotations

from langchain_chroma import Chroma

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit
from assistente_medico_api.services.rag_pipeline_service import (
    build_fallback_query,
    build_pipeline_audit,
    route_context_quality,
    run_load_memory,
    run_rerank_and_validate_context,
    run_retrieve,
    run_search_router,
)


def load_memory_node(state: ChatRAGState) -> dict:
    out = run_load_memory(dict(state))
    audit("rag_memory_loaded", kind="rag", memory_context=out.get("memory_context") or {})
    return out


def router_search_needed_node(state: ChatRAGState) -> dict:
    out = run_search_router(state.get("query") or "", state.get("memory_context"))
    audit("rag_search_router_done", kind="rag", router_decision=out.get("router_decision") or {})
    return {
        **out,
        "max_retrieve_attempts": int(state.get("max_retrieve_attempts") or 2),
        "rag_audit_payload": build_pipeline_audit({**dict(state), **out}),
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
    audit("rag_retrieve_attempt_done", kind="rag", retrieve_debug=out.get("retrieve_debug") or {})
    return {
        **out,
        "rag_audit_payload": build_pipeline_audit(merged),
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
    audit(
        "rag_rerank_validate_done",
        kind="rag",
        context_sufficient=out.get("context_sufficient"),
        insufficiency_reason=out.get("insufficiency_reason"),
        rerank_debug=out.get("rerank_debug") or {},
    )
    return {
        **out,
        "rag_audit_payload": build_pipeline_audit(merged),
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
    merged_candidates = previous + [
        doc for doc in out.get("candidate_docs") or []
        if (getattr(doc, "id", None), doc.metadata.get("source_stem"), doc.metadata.get("page_start")) not in {
            (getattr(prev, "id", None), prev.metadata.get("source_stem"), prev.metadata.get("page_start"))
            for prev in previous
        }
    ]
    out["candidate_docs"] = merged_candidates
    merged = {**dict(state), **out}
    audit("rag_fallback_retrieve_done", kind="rag", retrieve_debug=out.get("retrieve_debug") or {})
    return {
        **out,
        "rag_audit_payload": build_pipeline_audit(merged),
    }
