"""Recuperações Chroma/RAG para o fluxo de alertas (dois passeios ao vectorstore)."""

from __future__ import annotations

import logging

from langchain_chroma import Chroma

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.clinical_alert_state import ClinicalAlertGraphState
from assistente_medico_api.services.rag_pipeline_service import (
    format_source_label,
    run_rewrite_query,
    run_retrieve,
    run_rerank_and_validate_context,
)

_LOGGER = logging.getLogger("assistente_medico.alert_rag")


def _join_documents_text(docs: list, *, max_chars: int = 8000) -> str:
    chunks: list[str] = []
    used = 0
    for doc in docs:
        meta = getattr(doc, "metadata", {}) or {}
        diretriz = meta.get("diretriz") or meta.get("disease") or ""
        section = meta.get("section") or meta.get("header_1") or ""
        header = " | ".join(str(p) for p in (diretriz, section) if p)
        body = str(getattr(doc, "page_content", "") or "").strip()
        block = f"### {header}\n{body}" if header else body
        if not block.strip():
            continue
        fragment = block[:2600]
        if used + len(fragment) > max_chars:
            break
        chunks.append(fragment)
        used += len(fragment)
    return "\n\n".join(chunks)


async def node_retrieve_reference(
    state: ClinicalAlertGraphState,
    *,
    store: Chroma,
    settings: Settings,
) -> dict:
    """Primeira busca aos PCDTs (referências gerais do gatilho)."""
    query = (state.get("initial_query") or "").strip()
    steps = list(state.get("reasoning_steps") or [])
    if not query:
        steps.append("Recuperação PCDT (referência) ignorada: consulta inicial vazia.")
        return {
            "reference_rewrite": {},
            "reference_retrieve": {},
            "reference_rerank": {},
            "reference_docs_text": "",
            "reference_sources": [],
            "reasoning_steps": steps,
        }

    rw = run_rewrite_query(query, {}, settings)
    rewritten = rw.get("retrieval_query") or query
    structured = dict(rw.get("structured_terms") or {})
    clinical_understanding = dict(rw.get("clinical_understanding") or {})

    ret = run_retrieve(
        expanded_query=rewritten,
        structured_terms=structured,
        store=store,
        settings=settings,
        retrieve_attempt=1,
        fallback_query=None,
    )
    rer = await run_rerank_and_validate_context(
        query=query,
        expanded_query=rewritten,
        structured_terms=structured,
        clinical_understanding=clinical_understanding,
        candidate_docs=list(ret.get("candidate_docs") or []),
        settings=settings,
        trace=None,
    )
    retrieved = rer.get("retrieved_docs") or []
    docs_text = _join_documents_text(list(retrieved))
    sources = [format_source_label(d, i) for i, d in enumerate(retrieved, start=1)]
    steps.append(f"Primeira recuperação PCDT: {len(retrieved)} documento(s) após rerank.")

    _LOGGER.info(
        "alert retrieve reference trigger=%s patient=%s k=%s",
        state.get("trigger_type"),
        state.get("patient_id"),
        len(retrieved),
    )

    return {
        "reference_rewrite": rw.get("rewrite_result") or {},
        "reference_retrieve": ret.get("retrieve_result") or {},
        "reference_rerank": rer.get("rerank_result") or {},
        "reference_docs_text": docs_text,
        "reference_sources": sources,
        "reasoning_steps": steps,
    }


async def node_retrieve_patient_context(
    state: ClinicalAlertGraphState,
    *,
    store: Chroma,
    settings: Settings,
) -> dict:
    """Segunda busca aos PCDTs (contextualizada com achados prévios)."""
    query = (state.get("deep_query") or "").strip()
    ref_snip = (state.get("reference_docs_text") or "")[:2400]
    interpreted = dict(state.get("interpreted") or {})
    enriched = (
        f"{query}\n\n"
        "Resumo de achados locais antes da segunda recuperação:\n"
        f"{interpreted}\n\n"
        f"Trecho do contexto PCDT inicial (referência):\n{ref_snip}"
    ).strip()

    steps = list(state.get("reasoning_steps") or [])

    rw = run_rewrite_query(enriched, {}, settings)
    rewritten = rw.get("retrieval_query") or enriched
    structured = dict(rw.get("structured_terms") or {})
    clinical_understanding = dict(rw.get("clinical_understanding") or {})

    ret = run_retrieve(
        expanded_query=rewritten,
        structured_terms=structured,
        store=store,
        settings=settings,
        retrieve_attempt=2,
        fallback_query=None,
    )
    rer = await run_rerank_and_validate_context(
        query=enriched,
        expanded_query=rewritten,
        structured_terms=structured,
        clinical_understanding=clinical_understanding,
        candidate_docs=list(ret.get("candidate_docs") or []),
        settings=settings,
        trace=None,
    )
    retrieved = rer.get("retrieved_docs") or []
    docs_text = _join_documents_text(list(retrieved))
    sources = [format_source_label(d, i) for i, d in enumerate(retrieved, start=1)]
    steps.append(f"Segunda recuperação PCDT (contextual): {len(retrieved)} documento(s).")

    return {
        "patient_rewrite": rw.get("rewrite_result") or {},
        "patient_retrieve": ret.get("retrieve_result") or {},
        "patient_rerank": rer.get("rerank_result") or {},
        "patient_docs_text": docs_text,
        "patient_sources": sources,
        "reasoning_steps": steps,
    }
