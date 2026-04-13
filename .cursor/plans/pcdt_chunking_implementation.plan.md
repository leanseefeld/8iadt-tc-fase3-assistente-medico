---
name: PCDT Chunking Implementation
overview: "Implement `pcdt_ingest/chunk.py` (+ optional CLI) to turn per-page sidecars (`*.pages.jsonl`) into LangChain-ready chunks with a documented per-chunk metadata schema, two-pass MarkdownHeader + RecursiveCharacter split (~800-token-sized windows, ~150 overlap in character space). Dependencies: `langchain-text-splitters` + `langchain-core` in main `[project.dependencies]` (no optional extras)."
todos:
  - id: chunk-deps
    content: Add langchain-text-splitters + langchain-core to llm/pyproject [project.dependencies] (main group; no optional extras)
    status: completed
  - id: chunk-core
    content: Implement chunk.py — load JSONL, stitch + page map, MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter, metadata
    status: completed
  - id: chunk-output
    content: Write chunks to llm/data/chunks/pcdt/ (JSONL and/or pickle strategy) + optional manifest
    status: completed
  - id: chunk-cli
    content: Add chunk-pcdt entry point or document programmatic use; flags --max-files, --workers if batch
    status: completed
  - id: chunk-docs
    content: Update llm/README.md (pt-BR) with chunking step and dependencies
    status: completed
isProject: false
---

# Plan: PCDT chunking (`chunk.py`)

## Goal

Produce **retrieval-sized text chunks** from the **existing** extraction output (`*.pages.jsonl`), each with the **metadata schema** below (for RAG citations, filtering, and SFT). This unblocks **`embed.py`** (vector store) and **`sft.py`** (synthetic Q&A from chunk text).

## Metadata schema (per chunk)

Persisted JSONL rows (and `langchain_core.documents.Document.metadata`) should use **one consistent dict** per chunk. Field names are stable API for downstream code.

| Field | Type | Required | Description |
|--------|------|----------|-------------|
| `source_stem` | string | yes | Filename stem of the PCDT (e.g. `pcdt-da-artrite-psoriasica`), same as `{stem}` in `{stem}.pages.jsonl`. |
| `source_pdf` | string | yes | Path relative to `llm/data/`, e.g. `raw/pcdt/pcdt-da-artrite-psoriasica.pdf`, for citations and traceability. |
| `section` | string | yes | Human-readable section label for UI/prompts: fold active markdown headers from the first pass into one string (e.g. `"Tratamento > Imunobiológicos"` or a single `##` title if no nesting). Sub-chunks from the same header block repeat the **same** `section`. |
| `header_1` | string \| null | no | Title from the outermost configured header level (e.g. `##`), if present for this chunk. Easier filtering than parsing `section`. |
| `header_2` | string \| null | no | Title from the next header level (e.g. `###`), if present. Add `header_3` only if the splitter config uses deeper levels. |
| `page_start` | integer | yes | First PDF page (1-based) overlapping this chunk’s text. |
| `page_end` | integer | yes | Last PDF page (1-based, inclusive) overlapping this chunk’s text. |
| `page_range` | array | optional | Convenience copy: `[page_start, page_end]` — may be omitted if redundant. |
| `chunk_index` | integer | yes | Zero-based index of this chunk **within this PCDT** (`source_stem`), stable ordering for regeneration. |

**JSONL line shape** (one object per line):

```json
{
  "text": "<chunk plain text>",
  "metadata": {
    "source_stem": "pcdt-da-artrite-psoriasica",
    "source_pdf": "raw/pcdt/pcdt-da-artrite-psoriasica.pdf",
    "section": "Tratamento > Imunobiológicos",
    "header_1": "Tratamento",
    "header_2": "Imunobiológicos",
    "page_start": 14,
    "page_end": 15,
    "page_range": [14, 15],
    "chunk_index": 42
  }
}
```

In-memory **`Document`**: `page_content` = `text`; `metadata` = same keys except omit redundant `page_range` if desired.

## Inputs (contract)

- **Directory**: [`llm/data/processed/pcdt/`](../../llm/data/processed/pcdt)
- **Files**: `{stem}.pages.jsonl` — one JSON object per line:

```json
{"page": 1, "markdown": "## ..."}
```

- **Do not require** `{stem}.md`; reconstruction for splitting is done **in memory** from the JSONL lines (same as optional combined markdown, without writing a file).

## Algorithm

### 1) Stitch + page map

- Sort lines by `page` ascending.
- Concatenate `markdown` fields with `\n\n` between pages (match [`extract.combined_markdown_from_pages`](../../llm/src/pcdt_ingest/extract.py) behavior for consistency).
- Build a **character-offset → page** structure: e.g. list of `(global_start, global_end, page)` for each page’s slice in the stitched string, so any substring `[a, b)` can be mapped to min/max page touched.

### 2) First pass — `MarkdownHeaderTextSplitter`

- Use LangChain’s `MarkdownHeaderTextSplitter` with headers appropriate for PCDT structure (typically `##`, `###`; tune after sampling 2–3 protocols).
- Map splitter metadata keys to **`header_1`**, **`header_2`** (and **`section`**: breadcrumb string built from those titles) per the schema above.

### 3) Second pass — `RecursiveCharacterTextSplitter`

- Parameters aligned with [master RAG plan](rag_+_fine-tuning_pipeline_d9c3a9a0.plan.md): target **~800 tokens** effective chunk size and **~150 tokens** effective overlap. **For now**, implement with `chunk_size` / `chunk_overlap` in **characters** using a simple chars-per-token estimate (e.g. ~4 characters per token for PT-BR prose); refine with tokenizer-based splitting later if needed.
- Apply **per header-section** from pass 1 so headers are not split mid-section when possible.
- For each final chunk, compute **`page_start` / `page_end`** from the stitch map using the chunk’s start/end offsets in the full stitched text; set **`chunk_index`** in document order.

### 4) Output shape

- Prefer **`langchain_core.documents.Document`** in code (`page_content` + `metadata` matching the schema).
- **Persist** for inspection and for embed step, e.g.:

  - `llm/data/chunks/pcdt/{stem}.chunks.jsonl` — one JSON per line: `text` + `metadata` as specified, **or**
  - Single merged `pcdt_chunks.jsonl` with the same line shape (each line still carries `source_stem` inside `metadata`).

- Decide idempotency: re-run overwrites or versioned manifest line (lightweight `chunk_run.json` optional).

## Module & CLI

| Piece | Suggestion |
|-------|------------|
| **Module** | [`llm/src/pcdt_ingest/chunk.py`](../../llm/src/pcdt_ingest/chunk.py) — functions: `load_pages_jsonl`, `stitch_with_page_map`, `chunk_pcdt_document`, `write_chunks_jsonl` |
| **CLI** (optional but useful) | `chunk-pcdt` → `pcdt_ingest.cli_chunk:main` with `--max-files`, `--only-manifest` (reuse manifest PDF list pattern from [`cli_extract.py`](../../llm/src/pcdt_ingest/cli_extract.py)), `--pattern` / input dir defaulting to `processed/pcdt` |
| **Parallelism** | Optional **`--workers`** (thread pool) mirroring extraction — one file per worker; **default 1** for simpler debugging |

## Dependencies

- **`langchain-text-splitters`** and **`langchain-core`** (for `Document`).
- Add both to **`[project.dependencies]`** in [`llm/pyproject.toml`](../../llm/pyproject.toml) — same flat install as the rest of the package (`pip install -e .` from `llm/`), **no** optional dependency group for chunking.

## Edge cases

- **Empty or single-line pages**: still emit offsets; skip empty pages in stitch if needed.
- **Headers spanning pages**: stitched text preserves order; `page_range` reflects all pages overlapped by the chunk.
- **Very long sections**: second pass must split; metadata should keep the **same** `section` for all sub-chunks from that section.

## Validation

- Run on 2–3 real `*.pages.jsonl`; spot-check that `page_range` matches a manual lookup in the PDF/sidecar.
- Count chunks per document (~5k–15k total for ~132 PDFs is acceptable per master plan).

## Documentation

- Update [`llm/README.md`](../../llm/README.md) (pt-BR): prerequisite `extract-pcdt-markdown`, then `chunk-pcdt`, output paths; installation remains **`cd llm && pip install -e .`** (no extra extras for LangChain splitters once they are in main dependencies).

## Potential inefficiencies / optimizations

- **Character vs token sizing**: the ~800 / ~150 targets are **approximate** when using character `chunk_size` / `chunk_overlap`; acceptable until you need tighter alignment with a specific embedding model context window.
- **Duplicate text** across overlap regions: acceptable for retrieval; optional dedup by hash before embed.
- **Large JSONL outputs**: gzip or shard by stem if git or disk becomes an issue (out of scope unless needed).
