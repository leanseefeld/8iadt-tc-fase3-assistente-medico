"""Rewrite/query-understanding node for the RAG chat pipeline."""

from __future__ import annotations

import time

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate
from assistente_medico_api.services.rag_pipeline_service import append_audit_step, build_pipeline_audit, run_rewrite_query


async def rewrite_query_node(state: ChatRAGState, settings: Settings) -> dict:
    """Rewrite current question and produce structured clinical expansion."""
    t0 = time.perf_counter()
    out = run_rewrite_query(
        state.get("query") or "",
        state.get("memory_result") or state.get("memory_context"),
        settings,
    )
    steps = list(state.get("reasoning_steps") or [])
    steps.append(
        "Busca: pergunta reescrita e expandida com entendimento clínico estruturado."
    )
    merged = {**dict(state), **out, "reasoning_steps": steps}
    audit_trace = append_audit_step(
        merged,
        node="rewrite_query",
        input_summary={
            "query": state.get("query") or "",
            "memory_last_disease": (state.get("memory_result") or {}).get("last_disease"),
        },
        output_summary=out.get("rewrite_result") or {},
        settings=settings,
    )
    audit(
        "rag_rewrite_done",
        kind="rag",
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        patient_id=state.get("patient_id") or None,
        query_snippet=truncate(state.get("query") or ""),
        retrieval_query_snippet=truncate(out.get("retrieval_query") or ""),
        expanded_query_snippet=truncate(out.get("expanded_query") or ""),
        structured_terms=out.get("structured_terms") or {},
        catalog_candidates=out.get("catalog_candidates") or [],
    )
    return {
        **out,
        "reasoning_steps": steps,
        "audit_trace": audit_trace,
        "rag_audit_payload": build_pipeline_audit({**merged, "audit_trace": audit_trace}),
    }
