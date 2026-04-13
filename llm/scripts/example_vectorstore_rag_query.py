#!/usr/bin/env python3
"""
Exemplo: Consulta RAG ao Chroma PCDT baseada no turno de conversação (LangGraph).

Como funciona o fluxo (pipeline):
- O LangGraph precisa manter o histórico de mensagens (tipo chat) e passar a última pergunta
  do médico (isolada) para o nó de busca.
- A busca (retrieve) deve rodar **por turno**: usamos só a última pergunta/intenção do usuário 
  para o embedding, e não o bloco inteiro de texto. Isso garante mais precisão.
- Atenção: O modelo de embedding usado para buscar precisa ser o mesmo usado na ingestão (ex.: nomic-embed-text).
  Verifique se 'persist_directory' e 'collection_name' batem com 'build-vectorstore'.
- O resultado da busca alimenta o nó 'generate'. É lá que montamos o prompt com contexto e 
  as citações ('source_stem' / páginas).
- Métricas (k, filtros where) vêm do estado do grafo ou da configuração da sessão.

Para rodar (venv ativado):

    cd llm && python scripts/example_vectorstore_rag_query.py

Pré-requisitos: Ollama com 'nomic-embed-text' ativo e o banco de vetores já populado.
"""

from __future__ import annotations

import argparse
import textwrap

from langchain_core.documents import Document

from pcdt_ingest.embed import (
    CHROMA_COLLECTION_PCDT,
    build_ollama_embeddings,
    open_chroma_vectorstore,
)
from pcdt_ingest.paths import vectorstore_chroma_dir


def load_pcdt_chroma_store():
    """Abre o Chroma persistente com as mesmas opções da ingestão."""
    embeddings = build_ollama_embeddings()
    return open_chroma_vectorstore(
        persist_directory=vectorstore_chroma_dir(),
        embedding_function=embeddings,
        collection_name=CHROMA_COLLECTION_PCDT,
    )


def retrieve_for_conversation_turn(
    store,
    user_query: str,
    *,
    k: int = 4,
) -> list[tuple[Document, float]]:
    """
    Simula o nó de recuperação: embedding da pergunta atual + similaridade no Chroma.

    Em LangGraph, ``user_query`` seria tipicamente extraído do estado, por exemplo
    ``state["messages"][-1].content`` se a última mensagem for do médico.
    """
    # --- similarity_search_with_score: útil para threshold e debug de confiança ---
    return store.similarity_search_with_score(user_query, k=k)


def format_context_block(docs: list[Document]) -> str:
    """Formata trechos para colar num prompt de sistema ou mensagem de contexto."""
    parts: list[str] = []
    for i, doc in enumerate(docs, start=1):
        meta = doc.metadata
        stem = meta.get("source_stem", "?")
        p0 = meta.get("page_start", "?")
        p1 = meta.get("page_end", "?")
        header = f"[{i}] PCDT stem={stem} págs. {p0}-{p1}"
        parts.append(f"{header}\n{doc.page_content.strip()}")
    return "\n\n---\n\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exemplo de consulta ao vector store PCDT (RAG por turno).",
    )
    parser.add_argument(
        "-q",
        "--query",
        default=(
            "Quais são os critérios de inclusão para sgb?"
        ),
        help="Pergunta de exemplo (simula última mensagem do médico).",
    )
    parser.add_argument(
        "-k",
        type=int,
        default=4,
        help="Número de chunks a recuperar.",
    )
    args = parser.parse_args()

    store = load_pcdt_chroma_store()
    pairs = retrieve_for_conversation_turn(store, args.query, k=args.k)

    print(textwrap.dedent(f"""
        === Exemplo RAG (um turno da conversa) ===
        Query (última mensagem do médico): {args.query!r}
        Chunks: {len(pairs)} (k={args.k})
    """).strip())

    for rank, (doc, score) in enumerate(pairs, start=1):
        # Distância/score depende da implementação Chroma; tratar como comparável só entre runs.
        print(f"\n--- {rank} (score={score!r}) - Chunk {doc.id} ---")
        print(f"metadata: {doc.metadata}")
        preview = doc.page_content.strip().replace("\n", " ")[:320]
        print(f"texto (pré-visualização): {preview}...")

    docs_only = [d for d, _ in pairs]
    if docs_only:
        print("\n=== Bloco pronto para injetar no prompt do assistente ===\n")
        print(format_context_block(docs_only))
    else:
        print(
            "\n(Nenhum resultado — confirme que há vetores na coleção "
            f"«{CHROMA_COLLECTION_PCDT}» e que o Ollama está rodando.)"
        )


if __name__ == "__main__":
    main()
