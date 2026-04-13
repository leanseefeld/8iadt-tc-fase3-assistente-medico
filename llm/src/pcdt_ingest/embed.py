"""Embeddings locais (Ollama) e vector store Chroma para chunks PCDT."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings

from pcdt_ingest.logutil import get_logger
from pcdt_ingest.chunk import read_chunks_jsonl

_log = get_logger("embed")

CHROMA_COLLECTION_PCDT = "pcdt"
DEFAULT_OLLAMA_EMBED_MODEL = "nomic-embed-text"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_ADD_BATCH_SIZE = 64

# Tolerância para comparar ``st_mtime`` com valor vindo do JSONL do manifesto de embed.
_MTIME_EPS = 1e-6


def ollama_base_url() -> str:
    """URL base do Ollama (env ``OLLAMA_BASE_URL`` ou default local)."""
    return os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).strip() or DEFAULT_OLLAMA_BASE_URL


def build_ollama_embeddings(
    *,
    model: str = DEFAULT_OLLAMA_EMBED_MODEL,
    base_url: str | None = None,
) -> OllamaEmbeddings:
    return OllamaEmbeddings(model=model, base_url=base_url or ollama_base_url())


def filter_pcdt_chunk_manifest_rows(
    rows: Iterable[dict[str, Any]],
    data_base: Path,
) -> list[dict[str, Any]]:
    """
    Mantém entradas do manifesto de chunk com ``status`` ok/skipped, caminho relativo
    definido e ficheiro ``.chunks.jsonl`` existente sob ``data_base``.
    """
    out: list[dict[str, Any]] = []
    base = data_base.resolve()
    for row in rows:
        status = row.get("status")
        if status not in ("ok", "skipped"):
            continue
        rel = row.get("chunks_jsonl_relative_path")
        if not rel or not isinstance(rel, str):
            continue
        path = (base / rel).resolve()
        if not path.is_file():
            continue
        out.append(row)
    return out


def chroma_safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Chroma aceita metadados escalares (str, int, float, bool). Listas/objetos convertem-se.
    Chaves com valor ``None`` são omitidas.
    """
    safe: dict[str, Any] = {}
    for key, val in metadata.items():
        if val is None:
            continue
        if isinstance(val, (str, int, float, bool)):
            safe[key] = val
        elif isinstance(val, list):
            safe[key] = json.dumps(val, ensure_ascii=False)
        else:
            safe[key] = str(val)
    return safe


def documents_for_chroma(documents: list[Document]) -> list[Document]:
    """Cópias com metadados compatíveis com Chroma e IDs preservados."""
    out: list[Document] = []
    for doc in documents:
        if not doc.id:
            raise ValueError("documento sem id estável; chamar assign_stable_chunk_ids antes")
        meta = chroma_safe_metadata(doc.metadata)
        out.append(Document(page_content=doc.page_content, metadata=meta, id=doc.id))
    return out


def open_chroma_vectorstore(
    *,
    persist_directory: Path,
    embedding_function: OllamaEmbeddings,
    collection_name: str = CHROMA_COLLECTION_PCDT,
) -> Chroma:
    persist_directory.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=collection_name,
        embedding_function=embedding_function,
        persist_directory=str(persist_directory),
    )


def delete_vectors_for_source_stem(store: Chroma, source_stem: str) -> None:
    """Remove vetores cujo metadado ``source_stem`` coincide (reingestão idempotente)."""
    store.delete(where={"source_stem": source_stem})


def add_documents_batched(
    store: Chroma,
    documents: list[Document],
    *,
    batch_size: int = DEFAULT_ADD_BATCH_SIZE,
) -> None:
    """Adiciona documentos em lotes para reduzir picos de memória e carga no Ollama."""
    if batch_size < 1:
        raise ValueError("batch_size deve ser >= 1")
    # --- Loop em janelas: cada lote passa por ``add_documents`` (embeddings + persistência) ---
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        store.add_documents(batch)


def embed_one_stem(
    store: Chroma,
    chunks_jsonl: Path,
    *,
    source_stem: str,
    batch_size: int = DEFAULT_ADD_BATCH_SIZE,
) -> tuple[str, int]:
    """
    Apaga entradas antigas do stem, lê chunks do disco e volta a indexar.

    Devolve (status, embedded_count) com ``status`` em ``embedded``, ``skipped_empty``.
    """
    chunks_jsonl = chunks_jsonl.resolve()
    docs = read_chunks_jsonl(chunks_jsonl)
    if not docs:
        _log.info("%s: ficheiro de chunks vazio ou sem linhas JSON; remove vetores antigos", source_stem)
        delete_vectors_for_source_stem(store, source_stem)
        return "skipped_empty", 0

    # --- Substituir vetores deste documento antes de inserir lotes ---
    delete_vectors_for_source_stem(store, source_stem)
    ready = documents_for_chroma(docs)
    add_documents_batched(store, ready, batch_size=batch_size)
    return "embedded", len(ready)


def mtime_unchanged_vs_embed_manifest(stored_mtime: Any, current_mtime: float) -> bool:
    """Compara ``st_mtime`` atual com valor guardado no manifesto de embed (JSON)."""
    if stored_mtime is None:
        return False
    try:
        s = float(stored_mtime)
    except (TypeError, ValueError):
        return False
    return abs(s - float(current_mtime)) < _MTIME_EPS
