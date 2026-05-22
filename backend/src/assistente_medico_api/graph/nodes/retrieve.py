"""Nó de recuperação: similaridade no Chroma PCDT."""

from __future__ import annotations

import time

from langchain_chroma import Chroma
from langchain_core.documents import Document

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate


def format_source_label(doc: Document) -> str:
    """Rótulo amigável para a UI (alinhado ao exemplo RAG do repositório)."""
    meta = doc.metadata
    stem = meta.get("source_stem", "?")
    p0 = meta.get("page_start", "?")
    p1 = meta.get("page_end", "?")
    return f"PCDT {stem} (pp. {p0}-{p1})"


def format_context_block(docs: list[Document]) -> str:
    """Monta bloco de contexto para o prompt."""
    parts: list[str] = []
    for i, doc in enumerate(docs, start=1):
        meta = doc.metadata
        stem = meta.get("source_stem", "?")
        p0 = meta.get("page_start", "?")
        p1 = meta.get("page_end", "?")
        header = f"[{i}] PCDT stem={stem} págs. {p0}-{p1}"
        parts.append(f"{header}\n{doc.page_content.strip()}")
    return "\n\n---\n\n".join(parts)


def retrieve_node(
    state: ChatRAGState,
    *,
    store: Chroma,
    settings: Settings,
) -> dict:
    """
    Executa busca por similaridade usando retrieval_query (reescrita) quando existir.

    Síncrono para poder ser executado em asyncio.to_thread no endpoint.
    """
    pid = state.get("patient_id") or None
    t0 = time.perf_counter()
    query = (state.get("retrieval_query") or state.get("query") or "").strip()
    k = settings.retrieval_k
    pairs = store.similarity_search_with_score(query, k=k)
    docs = [d for d, _ in pairs]

    sources = [format_source_label(d) for d in docs]
    reasoning_steps = list(state.get("reasoning_steps") or [])
    reasoning_steps.append(
        f"Consultou a base PCDT com k={k} (consulta de busca: {query[:120]}{'…' if len(query) > 120 else ''})."
    )
    if docs:
        stems = sorted({d.metadata.get("source_stem", "?") for d in docs})
        reasoning_steps.append(f"Fragmentos de: {', '.join(stems)}.")
    else:
        reasoning_steps.append("Nenhum fragmento acima do limiar retornado.")

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    stems_list = sorted({d.metadata.get("source_stem", "?") for d in docs}) if docs else []
    audit(
        "rag_retrieve_done",
        kind="rag",
        latency_ms=latency_ms,
        patient_id=pid,
        retrieval_query_snippet=truncate(query),
        retrieved_count=len(docs),
        source_stems=stems_list,
        top_k=k,
    )

    return {
        "retrieved_docs": docs,
        "sources": sources,
        "reasoning_steps": reasoning_steps,
    }
