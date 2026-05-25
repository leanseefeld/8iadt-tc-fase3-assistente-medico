"""Nó de rerank e validação da suficiência do contexto."""

from __future__ import annotations

import time

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit
from assistente_medico_api.services.rag_pipeline_service import run_rerank_and_validate_context


async def rerank_and_validate_context_node(state: ChatRAGState, *, settings: Settings) -> dict:
    """Valida a qualidade do contexto e define o próximo passo do fluxo."""
    t0 = time.perf_counter()
    trace = list(state.get("aux_llm_trace") or [])
    out = await run_rerank_and_validate_context(
        query=state.get("query") or "",
        expanded_query=state.get("expanded_query") or state.get("retrieval_query") or "",
        structured_terms=state.get("structured_terms") or {},
        clinical_understanding=state.get("clinical_understanding") or {},
        candidate_docs=state.get("candidate_docs") or [],
        settings=settings,
        trace=trace,
    )
    current_attempt = int(state.get("retrieve_attempt") or 1)
    route = context_quality_router({**dict(state), **out, "max_retrieve_attempts": settings.rag_max_retrieve_attempts})
    steps = list(state.get("reasoning_steps") or [])
    steps.append(
        "Rerank: "
        + (
            "contexto suficiente para geração grounded."
            if route == "generate"
            else "contexto insuficiente; nova tentativa de busca será usada."
            if route == "retry_retrieve"
            else "contexto insuficiente; seguir para resposta de insuficiência."
        )
    )

    audit(
        "rag_rerank_validate_done",
        kind="rag",
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        patient_id=state.get("patient_id") or None,
        context_sufficient=out.get("context_sufficient"),
        insufficiency_reason=out.get("insufficiency_reason"),
        rerank_debug=out.get("rerank_debug") or {},
        rerank_route=route,
    )

    return {
        "retrieved_docs": out.get("retrieved_docs") or [],
        "sources": out.get("sources") or [],
        "context_sufficient": out.get("context_sufficient"),
        "insufficiency_reason": out.get("insufficiency_reason"),
        "rerank_result": out.get("rerank_result") or {},
        "rerank_debug": out.get("rerank_debug") or {},
        "max_retrieve_attempts": int(settings.rag_max_retrieve_attempts),
        "retrieve_attempt": current_attempt + 1 if route == "retry_retrieve" else current_attempt,
        "generation_mode": (
            "grounded_answer"
            if route == "generate" and out.get("context_sufficient")
            else "insufficient_context"
            if route == "generate"
            else state.get("generation_mode") or "grounded_answer"
        ),
        "rerank_decision": {"next_step": route},
        "reasoning_steps": steps,
        "aux_llm_trace": trace,
    }


def context_quality_router(state: ChatRAGState) -> str:
    """Seleciona a próxima aresta após a validação do contexto."""
    quality = (state.get("rerank_result") or {}).get("context_quality")
    if quality == "sufficient" or state.get("context_sufficient") is True:
        return "generate"

    attempts = int(state.get("retrieve_attempt") or 1)
    max_attempts = int(state.get("max_retrieve_attempts") or 1)
    if attempts < max_attempts:
        return "retry_retrieve"
    return "generate"
