"""Nó de recuperação: busca candidatos no Chroma."""

from __future__ import annotations

import time

from langchain_chroma import Chroma

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.context_formatting import format_context_block
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate
from assistente_medico_api.observability.clinical_audit_jsonl import ClinicalAuditAction, clinical_audit
from assistente_medico_api.services.rag_pipeline_service import format_source_label, run_retrieve


def _fallback_query(query: str, state: ChatRAGState) -> str:
    structured = state.get("structured_terms") or {}
    terms = [
        structured.get("diretriz") or structured.get("disease"),
        *(structured.get("preferred_sections") or []),
        *(structured.get("cid10_codes") or []),
        query,
    ]
    return " ".join(str(term).strip() for term in terms if str(term or "").strip())


def retrieve_node(
    state: ChatRAGState,
    *,
    store: Chroma,
    settings: Settings,
) -> dict:
    """Executa a busca inicial ou a tentativa de fallback interna."""
    t0 = time.perf_counter()
    retrieve_attempt = int(state.get("retrieve_attempt") or 1)
    structured_terms = state.get("structured_terms") or {}
    query = (state.get("expanded_query") or state.get("retrieval_query") or state.get("query") or "").strip()
    fallback_query = _fallback_query(state.get("query") or "", state) if retrieve_attempt > 1 else None

    out = run_retrieve(
        expanded_query=query,
        structured_terms=structured_terms,
        store=store,
        settings=settings,
        retrieve_attempt=retrieve_attempt,
        fallback_query=fallback_query,
    )

    steps = list(state.get("reasoning_steps") or [])
    debug = out.get("retrieve_debug") or {}
    steps.append(
        "Retrieve: buscou candidatos no Chroma "
        f"(attempt={out.get('retrieve_attempt')}, k={debug.get('k')}, candidatos={debug.get('candidate_count')})."
    )

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    pid = state.get("patient_id") or None
    candidate_docs = out.get("candidate_docs") or []
    stems_list = [d.metadata.get("source_stem") for d in candidate_docs if d.metadata.get("source_stem")]
    stems_resumo = stems_list[:15]

    audit(
        "rag_retrieve_done",
        kind="rag",
        latency_ms=latency_ms,
        patient_id=pid,
        retrieval_query_snippet=truncate(debug.get("query_sent_to_chroma") or ""),
        retrieve_attempt=out.get("retrieve_attempt"),
        candidate_count=debug.get("candidate_count"),
        metadata_filter=debug.get("metadata_filter"),
    )

    structured = structured_terms if isinstance(structured_terms, dict) else {}
    catalog_candidates = structured.get("catalog_candidates")
    clinical_audit(
        ClinicalAuditAction.RECUPERACAO_CONTEXTO_RAG,
        patient_id=pid,
        descricao=f"Recuperação RAG PCDT: {len(candidate_docs)} documento(s), {latency_ms} ms.",
        detalhes={
            "latency_ms": latency_ms,
            "documentos_recuperados": len(candidate_docs),
            "consulta_truncada": truncate(query, n=280),
            "consulta_expandida_truncada": truncate(query, n=280),
            "top_k": debug.get("k"),
            "stems_fonte_resumo": stems_resumo,
            "intencao_extracao": structured.get("intent"),
            "doenca_ou_diretriz_extracao": structured.get("diretriz") or structured.get("disease"),
            "candidatos_catalogo_quantidade": (
                len(catalog_candidates) if isinstance(catalog_candidates, list) else None
            ),
        },
        settings=settings,
    )

    return {
        "candidate_docs": out.get("candidate_docs") or [],
        "retrieve_result": out.get("retrieve_result") or {},
        "retrieve_debug": out.get("retrieve_debug") or {},
        "retrieve_attempt": out.get("retrieve_attempt") or retrieve_attempt,
        "reasoning_steps": steps,
    }
