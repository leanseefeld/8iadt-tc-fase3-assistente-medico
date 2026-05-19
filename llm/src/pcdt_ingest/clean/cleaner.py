"""Orquestra a limpeza de sidecars ``*.pages.jsonl``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pcdt_ingest.clean.heuristics import (
    cleaning_flag_for_reason,
    classify_document,
    default_config,
    find_clinical_content_start_page,
    is_broken_table_header_line,
    is_picture_text_end_line,
    is_picture_text_start_line,
    is_form_start_line,
    is_junk_text,
    is_malformed_table_block,
    is_markdown_heading_line,
    is_pcdt_title_line,
    is_table_line,
    is_table_caption_line,
    line_skip_reason,
    markdown_heading_level,
    repeated_edge_line_keys,
    split_table_cells,
)
from pcdt_ingest.clean.models import CleanConfig, CleanStats, DocumentClass, PageCleanResult
from pcdt_ingest.clean.utils import compact_spaces, dehyphenate, normalize_table_breaks, normalize_unicode
from pcdt_ingest.extract import PAGE_JSONL_SUFFIX
from pcdt_ingest.manifest import now_iso
from pcdt_ingest.paths import DIR_PROCESSED_PCDT, DIR_PROCESSED_PCDT_CLEANED, data_root

CLEANED_PAGE_JSONL_SUFFIX = ".pages.cleaned.jsonl"


def _append_flag(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)


def _remove_structural_noise_blocks(
    lines: list[str],
    *,
    flags: list[str],
    stats: CleanStats,
) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if is_form_start_line(line):
            removed = sum(1 for rest in lines[i:] if rest.strip())
            stats.lines_removed += removed
            _append_flag(flags, cleaning_flag_for_reason("form_block"))
            return out

        if is_broken_table_header_line(line):
            j = i + 1
            broken_headers = 1
            last_broken_header = i
            while j < len(lines):
                current = lines[j]
                if not current.strip() or is_markdown_heading_line(current):
                    break
                if is_broken_table_header_line(current):
                    broken_headers += 1
                    last_broken_header = j
                j += 1

            if broken_headers >= 2:
                remove_until = last_broken_header + 1
                while remove_until < len(lines) and is_table_line(lines[remove_until]):
                    remove_until += 1
                stats.lines_removed += sum(1 for item in lines[i:remove_until] if item.strip())
                _append_flag(flags, cleaning_flag_for_reason("malformed_table"))
                i = remove_until
                continue

        if is_table_line(line):
            j = i
            block: list[str] = []
            while j < len(lines) and (is_table_line(lines[j]) or not lines[j].strip()):
                block.append(lines[j])
                j += 1
            if is_malformed_table_block(block):
                stats.lines_removed += sum(1 for item in block if item.strip())
                _append_flag(flags, cleaning_flag_for_reason("malformed_table"))
                while out and not out[-1].strip():
                    out.pop()
                if out and is_table_caption_line(out[-1]):
                    out.pop()
                    stats.lines_removed += 1
                i = j
                continue
            out.extend(block)
            i = j
            continue

        out.append(line)
        i += 1
    return out


def _table_line_to_text(line: str) -> tuple[str, bool]:
    """Converte uma linha markdown table em texto plano orientado a embedding."""
    if not is_table_line(line):
        return line, False

    cells = []
    seen: set[str] = set()
    for cell in split_table_cells(line):
        cleaned = compact_spaces(cell).strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        cells.append(cleaned)

    if not cells:
        return "", True
    return " | ".join(cells), True


def _normalize_table_lines_for_rag(lines: list[str], *, flags: list[str]) -> list[str]:
    out: list[str] = []
    changed = False
    for line in lines:
        normalized, did_change = _table_line_to_text(line)
        changed = changed or did_change
        if normalized:
            out.append(normalized)
    if changed:
        _append_flag(flags, "normalized_table_rows")
    return out


def _normalize_clinical_headings_for_rag(lines: list[str], *, flags: list[str]) -> list[str]:
    """
    Promove títulos clínicos extraídos como texto plano para headings Markdown.

    O chunker usa MarkdownHeaderTextSplitter em ``##``/``###``. Sem esta etapa,
    páginas válidas como ``ANEXO`` + ``PROTOCOLO CLÍNICO...`` podem ser preservadas,
    mas ficam sem seção útil nos metadados do RAG.
    """
    out: list[str] = []
    changed = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue

        if is_pcdt_title_line(stripped) and not is_markdown_heading_line(stripped):
            out.append(f"## {stripped}")
            changed = True
            continue

        level = markdown_heading_level(stripped)
        if level is not None and level > 3 and is_pcdt_title_line(stripped):
            out.append(f"## {stripped.lstrip('#').strip()}")
            changed = True
            continue

        out.append(line)

    if changed:
        _append_flag(flags, "normalized_clinical_headings")
    return out


def read_page_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                continue
            rows.append(dict(obj))
    rows.sort(key=lambda r: int(r.get("page") or 0))
    return rows


def write_page_rows(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def clean_page_markdown(
    markdown: str,
    *,
    repeated_keys: set[str],
    config: CleanConfig,
) -> tuple[str, list[str], CleanStats]:
    flags: list[str] = []
    stats = CleanStats(pages_analyzed=1)

    text = normalize_unicode(markdown)
    table_text, table_changed = normalize_table_breaks(text)
    text = table_text
    if table_changed:
        flags.append("normalized_table_breaks")

    lines: list[str] = []
    in_picture_text_block = False
    for line in text.splitlines():
        if is_picture_text_start_line(line):
            in_picture_text_block = True
            stats.lines_removed += 1
            flag = cleaning_flag_for_reason("picture_text_block")
            if flag not in flags:
                flags.append(flag)
            continue
        if in_picture_text_block:
            stats.lines_removed += 1
            if is_picture_text_end_line(line):
                in_picture_text_block = False
            continue
        reason = line_skip_reason(line, repeated_keys)
        if reason is None:
            lines.append(line)
            continue
        stats.lines_removed += 1
        flag = cleaning_flag_for_reason(reason)
        _append_flag(flags, flag)
        if reason == "image_placeholder":
            stats.placeholders_removed += 1
        elif reason == "signature":
            stats.signatures_removed += 1
        elif reason == "page_number":
            stats.page_numbers_removed += 1
        elif reason == "header_footer":
            stats.headers_footers_removed += 1

    lines = _remove_structural_noise_blocks(lines, flags=flags, stats=stats)
    lines = _normalize_clinical_headings_for_rag(lines, flags=flags)
    lines = _normalize_table_lines_for_rag(lines, flags=flags)
    text = "\n".join(lines)
    text, did_dehyphenate = dehyphenate(text)
    if did_dehyphenate:
        flags.append("dehyphenated")
        stats.dehyphenated_pages += 1
    text = compact_spaces(text)

    if is_junk_text(text, min_words=config.min_words):
        flags.append("junk_text")
        stats.junk_detected += 1

    return text, flags, stats


def clean_pages(
    rows: list[dict[str, Any]],
    *,
    config: CleanConfig | None = None,
) -> tuple[list[PageCleanResult], CleanStats, DocumentClass]:
    cfg = config or default_config()
    original_texts = [str(row.get("markdown") or "") for row in rows]
    repeated_keys = repeated_edge_line_keys(
        original_texts,
        threshold=cfg.header_footer_threshold,
        window=cfg.header_footer_window,
    )
    clinical_start_page = find_clinical_content_start_page(rows)
    doc_class = classify_document(original_texts)

    results: list[PageCleanResult] = []
    total = CleanStats()
    for row in rows:
        page = int(row.get("page") or 0)
        original = str(row.get("markdown") or "")
        cleaned, flags, stats = clean_page_markdown(
            original,
            repeated_keys=repeated_keys,
            config=cfg,
        )
        skipped = False
        skip_reason: str | None = None
        if cfg.skip_initial_admin_pages and page and page < clinical_start_page:
            skipped = True
            skip_reason = "before_clinical_content"
        elif "junk_text" in flags:
            skipped = True
            skip_reason = "junk_text"

        out = dict(row)
        out["markdown"] = "" if skipped else cleaned

        if skipped:
            stats.pages_skipped += 1
        else:
            stats.pages_written += 1
        total.merge(stats)
        results.append(
            PageCleanResult(
                record=out,
                original_markdown=original,
                cleaned_markdown=cleaned,
                flags=flags,
                skipped=skipped,
                skip_reason=skip_reason,
                stats=stats,
            )
        )

    return results, total, doc_class


def default_cleaned_processed_dir() -> Path:
    """Diretório padrão para sidecars limpos."""
    return data_root() / DIR_PROCESSED_PCDT_CLEANED


def default_output_path(input_path: Path, *, output_dir: Path | None = None) -> Path:
    out_name = (
        input_path.name[: -len(".pages.jsonl")] + CLEANED_PAGE_JSONL_SUFFIX
        if input_path.name.endswith(".pages.jsonl")
        else input_path.name + ".cleaned.jsonl"
    )
    if output_dir is not None:
        return output_dir / out_name
    try:
        rel_parent = input_path.parent.resolve().relative_to(data_root().resolve())
    except ValueError:
        rel_parent = None
    if rel_parent == DIR_PROCESSED_PCDT:
        return default_cleaned_processed_dir() / out_name
    if input_path.name.endswith(".pages.jsonl"):
        return input_path.with_name(out_name)
    return input_path.with_suffix(input_path.suffix + ".cleaned.jsonl")


def clean_pages_jsonl(
    input_path: Path,
    *,
    output_path: Path | None = None,
    config: CleanConfig | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[CleanStats, Path, DocumentClass]:
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    out = output_path or default_output_path(input_path)
    if out.exists() and not force and not dry_run and out.stat().st_mtime >= input_path.stat().st_mtime:
        raise FileExistsError(f"arquivo de saída já existe: {out}")

    rows = read_page_rows(input_path)
    results, stats, doc_class = clean_pages(rows, config=config)
    if not dry_run:
        write_page_rows([result.record for result in results], out)
    return stats, out, doc_class


def clean_one_stem(
    stem: str,
    *,
    processed_dir: Path,
    cleaned_dir: Path,
    data_base: Path,
    force: bool,
    dry_run: bool = False,
    config: CleanConfig | None = None,
) -> dict[str, Any]:
    """Processa ``processed_dir/<stem>.pages.jsonl`` e retorna uma linha de manifesto."""
    ts = now_iso()
    pages_path = processed_dir / f"{stem}{PAGE_JSONL_SUFFIX}"
    out_path = cleaned_dir / f"{stem}{CLEANED_PAGE_JSONL_SUFFIX}"
    rel_pages = pages_path.resolve().relative_to(data_base.resolve()).as_posix()
    rel_cleaned = out_path.resolve().relative_to(data_base.resolve()).as_posix()

    base: dict[str, Any] = {
        "source_stem": stem,
        "pages_jsonl_relative_path": rel_pages,
        "cleaned_pages_jsonl_relative_path": rel_cleaned,
        "status": "error",
        "error": None,
        "document_class": None,
        "cleaned_at": ts,
    }

    if not pages_path.is_file():
        return {
            **base,
            "error": "ficheiro .pages.jsonl inexistente",
            "stats": CleanStats().as_dict(),
        }

    if (
        not force
        and not dry_run
        and out_path.is_file()
        and out_path.stat().st_mtime >= pages_path.stat().st_mtime
    ):
        return {
            **base,
            "status": "skipped",
            "stats": CleanStats().as_dict(),
        }

    try:
        stats, _written, doc_class = clean_pages_jsonl(
            pages_path,
            output_path=out_path,
            config=config,
            dry_run=dry_run,
            force=force,
        )
    except Exception as exc:
        return {
            **base,
            "error": str(exc),
            "stats": CleanStats().as_dict(),
        }

    return {
        **base,
        "status": "dry_run" if dry_run else "ok",
        "document_class": doc_class,
        "stats": stats.as_dict(),
    }
