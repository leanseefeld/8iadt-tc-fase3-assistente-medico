"""LangGraph node: rerank candidates and validate context quality."""

from __future__ import annotations

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit
from assistente_medico_api.services.rag_pipeline_service import (
    append_audit_step,
    build_pipeline_audit,
    route_context_quality,
    run_rerank_and_validate_context,
)


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
