"""CLI para pós-processar um arquivo `.chunks.jsonl` juntando chunks adjacentes fracionados.

Uso: python -m pcdt_ingest.cli_merge_chunks path/to/stem.chunks.jsonl
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pcdt_ingest.chunk import _join_semantic_chunks
from pcdt_ingest.pipeline_config import get_config


def _meta_eq(a: dict[str, Any], b: dict[str, Any]) -> bool:
    keys = ("header_1", "header_2", "page_start", "page_end")
    for k in keys:
        if a.get(k) != b.get(k):
            return False
    return True


def _should_merge_texts(left: str, right: str) -> bool:
    l = left.rstrip()
    r = right.lstrip()
    if not l or not r:
        return True
    # if left ends with terminal punctuation, avoid merging
    if any(l.endswith(ch) for ch in (".", "!", "?", "…")):
        return False
    # if right starts with lowercase, likely continuation
    if r and r[0].islower():
        return True
    # common Portuguese prepositions at end
    if l.split() and l.split()[-1].lower() in {
        "de",
        "do",
        "da",
        "dos",
        "das",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "para",
        "por",
        "com",
        "sem",
        "sob",
        "sobre",
    }:
        return True
    if len(l) < 200:
        return True
    return False


def merge_chunks_file(path: Path) -> int:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows = []
    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    if not rows:
        return 0

    merged: list[dict[str, Any]] = []
    cur = rows[0].copy()
    for nxt in rows[1:]:
        if _meta_eq(cur.get("metadata", {}), nxt.get("metadata", {})) and _should_merge_texts(
            cur.get("text", ""), nxt.get("text", "")
        ):
            cur_text = _join_semantic_chunks(cur.get("text", ""), nxt.get("text", ""))
            cur["text"] = cur_text
            # prefer the widest page range
            m = cur.setdefault("metadata", {})
            nm = nxt.get("metadata", {})
            try:
                m_ps = int(m.get("page_start", 0))
                m_pe = int(m.get("page_end", 0))
                n_ps = int(nm.get("page_start", 0))
                n_pe = int(nm.get("page_end", 0))
                m["page_start"] = min(m_ps, n_ps) if m_ps and n_ps else m_ps or n_ps
                m["page_end"] = max(m_pe, n_pe) if m_pe and n_pe else m_pe or n_pe
            except Exception:
                pass
        else:
            merged.append(cur)
            cur = nxt.copy()
    merged.append(cur)

    # reindex chunk_index
    for i, r in enumerate(merged):
        if "metadata" in r:
            r["metadata"]["chunk_index"] = i

    # write back
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in merged:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return len(merged)


def update_manifest(manifest_path: Path, source_stem: str, new_count: int) -> None:
    if not manifest_path.is_file():
        return
    out_lines = []
    changed = False
    with manifest_path.open(encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            row = json.loads(raw)
            if row.get("source_stem") == source_stem:
                row["chunk_count"] = new_count
                row["chunked_at"] = datetime.now(timezone.utc).isoformat()
                changed = True
            out_lines.append(row)
    if changed:
        with manifest_path.open("w", encoding="utf-8") as f:
            for r in out_lines:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge adjacent chunks in a .chunks.jsonl file")
    parser.add_argument("path", help="path to .chunks.jsonl file")
    parser.add_argument("--manifest", help="path to manifest jsonl (pcdt_chunk_index.jsonl)")
    args = parser.parse_args(argv)

    p = Path(args.path)
    new_count = merge_chunks_file(p)
    print(f"Merged chunks written: {p} -> new_count={new_count}")
    if args.manifest:
        update_manifest(Path(args.manifest), p.stem.replace(".chunks", ""), new_count)
        print("Manifest updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

