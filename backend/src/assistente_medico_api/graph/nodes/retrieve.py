"""Nó de recuperação: similaridade no Chroma PCDT."""

from __future__ import annotations

from langchain_chroma import Chroma
from langchain_core.documents import Document

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.state import ChatRAGState


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
    Executa busca por similaridade na última mensagem do usuário.

    Síncrono para poder ser executado em asyncio.to_thread no endpoint.
    """
    query = state.get("query") or ""
    k = settings.retrieval_k
    pairs = store.similarity_search_with_score(query, k=k)
    docs = [d for d, _ in pairs]

    sources = [format_source_label(d) for d in docs]
    reasoning_steps = [
        f"Consultou a base PCDT com k={k} para a pergunta atual.",
    ]
    if docs:
        stems = sorted({d.metadata.get("source_stem", "?") for d in docs})
        reasoning_steps.append(f"Fragmentos de: {', '.join(stems)}.")
    else:
        reasoning_steps.append("Nenhum fragmento acima do limiar retornado.")

    return {
        "retrieved_docs": docs,
        "sources": sources,
        "reasoning_steps": reasoning_steps,
    }
