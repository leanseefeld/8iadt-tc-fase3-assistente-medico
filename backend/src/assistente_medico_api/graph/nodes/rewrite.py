"""Nó de reescrita da pergunta para recuperação (RAG conversacional)."""

from __future__ import annotations

import time

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate
from assistente_medico_api.services.rag_query_expansion_service import (
    expand_query_for_retrieval,
    resolve_retrieval_query,
)


async def rewrite_query_node(state: ChatRAGState, settings: Settings) -> dict:
    """Reescreve a pergunta e aplica expansão estruturada para busca."""
    query = (state.get("query") or "").strip()
    t0 = time.perf_counter()

    resolution = await resolve_retrieval_query(state=dict(state), query=query, settings=settings)
    expansion = expand_query_for_retrieval(
        query=query,
        retrieval_query=resolution.retrieval_query,
    )

    steps = list(resolution.reasoning_steps)
    steps.append("Busca: consulta expandida com termos clínicos estruturados.")

    audit(
        "rag_rewrite_done",
        kind="rag",
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        patient_id=state.get("patient_id") or None,
        query_snippet=truncate(query),
        retrieval_query_snippet=truncate(resolution.retrieval_query),
        expanded_query_snippet=truncate(expansion.expanded_query),
        used_history=resolution.used_history,
    )

    return {
        "retrieval_query": resolution.retrieval_query,
        "expanded_query": expansion.expanded_query,
        "clinical_understanding": expansion.clinical_understanding,
        "structured_terms": expansion.structured_terms,
        "query_expansion": expansion.query_expansion,
        "reasoning_steps": steps,
    }
