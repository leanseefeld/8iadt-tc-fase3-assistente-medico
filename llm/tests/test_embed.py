"""Testes unitários do filtro de manifesto e parsing de chunks (sem Ollama/Chroma)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcdt_ingest.embed import (
    chroma_safe_metadata,
    filter_pcdt_chunk_manifest_rows,
    mtime_unchanged_vs_embed_manifest,
)
from pcdt_ingest.chunk import parse_chunks_jsonl_line, read_chunks_jsonl


def test_filter_pcdt_chunk_manifest_rows(tmp_path: Path) -> None:
    data = tmp_path / "llm" / "data"
    chunks_dir = data / "chunks" / "pcdt"
    chunks_dir.mkdir(parents=True)
    f_ok = chunks_dir / "a.chunks.jsonl"
    f_ok.write_text('{"text":"x","metadata":{}}\n', encoding="utf-8")

    rows = [
        {"source_stem": "a", "status": "ok", "chunks_jsonl_relative_path": "chunks/pcdt/a.chunks.jsonl"},
        {"source_stem": "b", "status": "ok", "chunks_jsonl_relative_path": "chunks/pcdt/missing.chunks.jsonl"},
        {"source_stem": "c", "status": "error", "chunks_jsonl_relative_path": "chunks/pcdt/c.chunks.jsonl"},
        {"source_stem": "d", "status": "skipped", "chunks_jsonl_relative_path": ""},
    ]
    got = filter_pcdt_chunk_manifest_rows(rows, data)
    assert len(got) == 1
    assert got[0]["source_stem"] == "a"


def test_parse_and_read_chunks_jsonl(tmp_path: Path) -> None:
    meta = {
        "source_stem": "doc1",
        "source_pdf": "raw/pcdt/doc1.pdf",
        "chunk_index": 0,
        "page_start": 1,
        "page_end": 2,
        "page_range": [1, 2],
    }
    line = json.dumps({"text": "hello", "metadata": meta}, ensure_ascii=False)
    doc = parse_chunks_jsonl_line(line)
    assert doc.page_content == "hello"
    assert doc.metadata["chunk_index"] == 0

    path = tmp_path / "x.chunks.jsonl"
    path.write_text(line + "\n\n" + line.replace("chunk_index\": 0", "chunk_index\": 1") + "\n", encoding="utf-8")
    docs = read_chunks_jsonl(path)
    assert len(docs) == 2
    assert docs[0].id == "doc1:0"
    assert docs[1].id == "doc1:1"


def test_chroma_safe_metadata_list_to_json_string() -> None:
    meta = {"source_stem": "s", "page_range": [1, 3], "n": 1, "flag": True}
    safe = chroma_safe_metadata(meta)
    assert safe["page_range"] == "[1, 3]"
    assert safe["n"] == 1
    assert safe["flag"] is True


@pytest.mark.parametrize(
    ("stored", "current", "expected"),
    [
        (100.0, 100.0, True),
        (100.0, 200.0, False),
        (None, 100.0, False),
        ("bad", 1.0, False),
    ],
)
def test_mtime_unchanged_vs_embed_manifest(
    stored: object,
    current: float,
    expected: bool,
) -> None:
    assert mtime_unchanged_vs_embed_manifest(stored, current) is expected
