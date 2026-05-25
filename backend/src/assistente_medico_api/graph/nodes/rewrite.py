"""Nó de reescrita da pergunta para recuperação (RAG conversacional)."""

from __future__ import annotations

import time

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate
from assistente_medico_api.observability.clinical_audit_jsonl import ClinicalAuditAction, clinical_audit

_REWRITE_SYSTEM = """\
Você reformula a última pergunta do médico como uma única consulta autocontida para busca \
por similaridade em documentos dos Protocolos Clínicos e Diretrizes Terapêuticas (PCDT) do Brasil.
Preserve termos clínicos e CID/procedimentos quando citados no histórico.
Responda apenas com a consulta reformulada, sem prefixos nem explicações.\
"""


def _history_transcript(state: ChatRAGState) -> str:
    lines: list[str] = []
    for turn in state.get("chat_history") or []:
        text = (turn.get("content") or "").strip()
        if not text:
            continue
        role = turn.get("role")
        if role == "user":
            lines.append(f"Médico: {text}")
        elif role == "assistant":
            lines.append(f"Assistente: {text}")
    return "\n".join(lines)
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
        settings=settings,
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
        "matched_cid10_codes": expansion.matched_cid10_codes,
        "matched_diseases": expansion.matched_diseases,
        "matched_medications": expansion.matched_medications,
        "query_expansion": expansion.query_expansion,
        "reasoning_steps": steps,
    }
