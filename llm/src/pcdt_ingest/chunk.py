"""Fragmentação de sidecars ``*.pages.jsonl`` em chunks com metadata (seção, páginas)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from pcdt_ingest.extract import PAGE_JSONL_SUFFIX, PageRecord, read_pages_jsonl
from pcdt_ingest.logutil import get_logger
from pcdt_ingest.paths import DIR_RAW_PCDT, DIR_CHUNKS_PCDT, data_root

_log = get_logger("chunk")

# Estimativa simples ~4 caracteres por token (PT-BR); alvo ~800 / ~150 tokens.
_CHARS_PER_TOKEN = 4
_CHUNK_TOKENS = 800
_OVERLAP_TOKENS = 150

CHUNK_JSONL_SUFFIX = ".chunks.jsonl"

# Cabeçalhos markdown típicos em PCDT (ajustável).
_DEFAULT_HEADER_SPLITS: list[tuple[str, str]] = [
    ("##", "header_1"),
    ("###", "header_2"),
]


def stitch_with_page_spans(
    pages: list[PageRecord],
) -> tuple[str, list[tuple[int, int, int]]]:
    """
    Concatena páginas com ``\\n\\n`` e regista intervalos globais [start, end) por página.
    """
    if not pages:
        return "", []
    pieces: list[str] = []
    spans: list[tuple[int, int, int]] = []
    offset = 0
    for i, rec in enumerate(pages):
        if i > 0:
            offset += 2  # ``\\n\\n`` entre páginas
        start = offset
        text = rec.markdown
        end = start + len(text)
        spans.append((start, end, rec.page))
        offset = end
        pieces.append(text)
    return "\n\n".join(pieces), spans


def page_range_for_char_span(
    spans: list[tuple[int, int, int]],
    gstart: int,
    gend: int,
) -> tuple[int, int]:
    """Devolve (page_start, page_end) inclusivos para o intervalo de caracteres [gstart, gend)."""
    touched: list[int] = []
    for s, e, p in spans:
        if gstart < e and gend > s:
            touched.append(p)
    if not touched:
        return 1, 1
    return min(touched), max(touched)


def _section_breadcrumb(meta: dict[str, Any]) -> str:
    parts: list[str] = []
    for k in ("header_1", "header_2"):
        v = meta.get(k)
        if v is not None and str(v).strip():
            parts.append(str(v).strip())
    if parts:
        return " > ".join(parts)
    return "(sem cabeçalho)"


def _align_sections_to_full_text(
    full_text: str,
    section_docs: list[Document],
) -> list[tuple[Document, int, int]]:
    """Associa cada seção ao intervalo global [start, end) em ``full_text``."""
    aligned: list[tuple[Document, int, int]] = []
    pos = 0
    for doc in section_docs:
        body = doc.page_content
        if not body:
            aligned.append((doc, pos, pos))
            continue
        idx = full_text.find(body, pos)
        if idx == -1:
            stripped = body.lstrip()
            idx = full_text.find(stripped, pos) if stripped else -1
        if idx == -1:
            idx = pos
        start = idx
        end = start + len(body)
        pos = max(pos, end)
        aligned.append((doc, start, end))
    return aligned


def _split_section_recursive(
    section_doc: Document,
    *,
    global_start: int,
    rec: RecursiveCharacterTextSplitter,
) -> list[tuple[str, dict[str, Any], int, int]]:
    """
    Parte o texto da seção em chunks; devolve lista de
    (texto, metadados base, char_global_start, char_global_end).
    """
    section_text = section_doc.page_content
    base_meta = dict(section_doc.metadata)
    if not section_text.strip():
        return []

    # --- Segundo passe: ``RecursiveCharacterTextSplitter`` por seção ---
    mini_docs = rec.split_documents(
        [Document(page_content=section_text, metadata=base_meta)]
    )
    out: list[tuple[str, dict[str, Any], int, int]] = []
    overlap = getattr(rec, "chunk_overlap", 0)
    search_at = 0
    for mini in mini_docs:
        piece = mini.page_content
        j = section_text.find(piece, search_at)
        if j == -1:
            j = section_text.find(piece.strip(), search_at)
        if j == -1:
            j = search_at
        local_start = j
        local_end = j + len(piece)
        search_at = max(search_at, j + max(1, len(piece) - overlap))
        g0 = global_start + local_start
        g1 = global_start + local_end
        out.append((piece, dict(mini.metadata), g0, g1))
    return out


def chunk_pages_to_documents(
    pages: list[PageRecord],
    *,
    source_stem: str,
    source_pdf_rel: str,
    headers_to_split_on: list[tuple[str, str]] | None = None,
    chunk_tokens: int = _CHUNK_TOKENS,
    overlap_tokens: int = _OVERLAP_TOKENS,
    chars_per_token: int = _CHARS_PER_TOKEN,
) -> list[Document]:
    """
    Produz ``Document`` LangChain por chunk com metadata alinhada ao schema do plano.
    """
    full_text, page_spans = stitch_with_page_spans(pages)
    if not full_text.strip():
        return []

    headers_to_split_on = headers_to_split_on or _DEFAULT_HEADER_SPLITS
    md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    section_docs = md_splitter.split_text(full_text)

    chunk_size = chunk_tokens * chars_per_token
    chunk_overlap = overlap_tokens * chars_per_token
    rec = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    aligned = _align_sections_to_full_text(full_text, section_docs)

    documents: list[Document] = []
    chunk_index = 0

    for section_doc, g_sec_start, _g_sec_end in aligned:
        triples = _split_section_recursive(
            section_doc,
            global_start=g_sec_start,
            rec=rec,
        )
        for piece_text, sec_meta, g0, g1 in triples:
            ps, pe = page_range_for_char_span(page_spans, g0, g1)
            h1 = sec_meta.get("header_1")
            h2 = sec_meta.get("header_2")
            meta: dict[str, Any] = {
                "source_stem": source_stem,
                "source_pdf": source_pdf_rel,
                "section": _section_breadcrumb(sec_meta),
                "header_1": h1 if h1 is not None else None,
                "header_2": h2 if h2 is not None else None,
                "page_start": ps,
                "page_end": pe,
                "page_range": [ps, pe],
                "chunk_index": chunk_index,
            }
            documents.append(Document(page_content=piece_text, metadata=meta))
            chunk_index += 1

    return documents


def default_chunks_dir() -> Path:
    return data_root() / DIR_CHUNKS_PCDT


def source_pdf_relative(stem: str) -> str:
    """Caminho ``raw/pcdt/<stem>.pdf`` relativo a ``llm/data``."""
    return (DIR_RAW_PCDT / f"{stem}.pdf").as_posix()


def write_chunks_jsonl(documents: list[Document], path: Path) -> None:
    """Grava uma linha JSON por chunk: ``text`` + ``metadata``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for doc in documents:
            row = {
                "text": doc.page_content,
                "metadata": doc.metadata,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_chunks_jsonl_line(line: str) -> Document:
    """Uma linha do formato gravado por ``write_chunks_jsonl`` → ``Document``."""
    row = json.loads(line)
    text = row["text"]
    meta = dict(row["metadata"])
    return Document(page_content=text, metadata=meta)


def assign_stable_chunk_ids(documents: list[Document]) -> None:
    """Define ``doc.id`` como ``{source_stem}:{chunk_index}`` para idempotência no Chroma."""
    for doc in documents:
        stem = doc.metadata.get("source_stem")
        idx = doc.metadata.get("chunk_index")
        if stem is None or idx is None:
            raise ValueError("metadata deve incluir source_stem e chunk_index")
        doc.id = f"{stem}:{idx}"


def read_chunks_jsonl(path: Path) -> list[Document]:
    """Lê ``*.chunks.jsonl``; arquivo vazio ou só linhas em branco → lista vazia."""
    documents: list[Document] = []
    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            documents.append(parse_chunks_jsonl_line(line))
    assign_stable_chunk_ids(documents)
    return documents


def chunk_sidecar_file(
    pages_jsonl: Path,
    *,
    output_path: Path | None = None,
    **kwargs: Any,
) -> tuple[list[Document], Path]:
    """
    Lê ``{stem}.pages.jsonl``, grava ``{stem}.chunks.jsonl`` e devolve documentos + caminho.
    """
    stem = pages_jsonl.name[: -len(PAGE_JSONL_SUFFIX)]
    if not pages_jsonl.is_file():
        raise FileNotFoundError(pages_jsonl)

    pages = read_pages_jsonl(pages_jsonl)
    source_pdf_rel = source_pdf_relative(stem)
    docs = chunk_pages_to_documents(
        pages,
        source_stem=stem,
        source_pdf_rel=source_pdf_rel,
        **kwargs,
    )
    out = output_path if output_path is not None else default_chunks_dir() / f"{stem}{CHUNK_JSONL_SUFFIX}"
    write_chunks_jsonl(docs, out)
    return docs, out


def chunk_one_stem(
    stem: str,
    *,
    processed_dir: Path,
    chunks_dir: Path,
    data_base: Path,
    force: bool,
    **chunk_kw: Any,
) -> dict[str, Any]:
    """
    Processa um stem: lê ``processed_dir/<stem>.pages.jsonl``, escreve ``chunks_dir/<stem>.chunks.jsonl``.
    Retorna linha de manifesto.
    """
    from pcdt_ingest.manifest import now_iso

    ts = now_iso()
    pages_path = processed_dir / f"{stem}{PAGE_JSONL_SUFFIX}"
    out_path = chunks_dir / f"{stem}{CHUNK_JSONL_SUFFIX}"
    rel_pages = pages_path.resolve().relative_to(data_base.resolve()).as_posix()
    rel_chunks = out_path.resolve().relative_to(data_base.resolve()).as_posix()

    if not pages_path.is_file():
        return {
            "source_stem": stem,
            "pages_jsonl_relative_path": rel_pages,
            "chunks_jsonl_relative_path": rel_chunks,
            "status": "error",
            "error": "ficheiro .pages.jsonl inexistente",
            "chunk_count": 0,
            "chunked_at": ts,
        }

    if (
        not force
        and out_path.is_file()
        and out_path.stat().st_mtime >= pages_path.stat().st_mtime
    ):
        return {
            "source_stem": stem,
            "pages_jsonl_relative_path": rel_pages,
            "chunks_jsonl_relative_path": rel_chunks,
            "status": "skipped",
            "error": None,
            "chunk_count": 0,
            "chunked_at": ts,
        }

    try:
        docs, written = chunk_sidecar_file(
            pages_path,
            output_path=out_path,
            **chunk_kw,
        )
    except Exception as e:
        _log.exception("Falha ao fragmentar %s", stem)
        return {
            "source_stem": stem,
            "pages_jsonl_relative_path": rel_pages,
            "chunks_jsonl_relative_path": rel_chunks,
            "status": "error",
            "error": str(e),
            "chunk_count": 0,
            "chunked_at": ts,
        }

    return {
        "source_stem": stem,
        "pages_jsonl_relative_path": rel_pages,
        "chunks_jsonl_relative_path": rel_chunks,
        "status": "ok",
        "error": None,
        "chunk_count": len(docs),
        "chunked_at": ts,
    }
