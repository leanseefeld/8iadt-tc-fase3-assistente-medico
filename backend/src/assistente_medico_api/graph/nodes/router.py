"""LangGraph node: decide whether the current turn needs RAG search."""

from __future__ import annotations

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit
from assistente_medico_api.services.rag_pipeline_service import append_audit_step, build_pipeline_audit, run_search_router


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
        "max_retrieve_attempts": int(state.get("max_retrieve_attempts") or getattr(settings, "rag_max_retrieve_attempts", 2)),
        "audit_trace": audit_trace,
        "rag_audit_payload": build_pipeline_audit({**dict(state), **out, "audit_trace": audit_trace}),
    }


def route_search_needed(state: ChatRAGState) -> str:
    return "rag" if state.get("search_needed") else "direct"
