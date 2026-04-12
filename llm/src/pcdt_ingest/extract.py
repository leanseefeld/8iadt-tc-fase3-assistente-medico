"""Extração de PDF PCDT para Markdown por página (sidecar JSONL) e MD combinado opcional."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf4llm

from pcdt_ingest.logutil import get_logger
from pcdt_ingest.manifest import now_iso
from pcdt_ingest.paths import DIR_PROCESSED_PCDT, data_root

_log = get_logger("extract")

# Sufixo do sidecar JSONL (uma linha por página) junto a ``processed/pcdt/<stem>.pdf``.
PAGE_JSONL_SUFFIX = ".pages.jsonl"

# Junta páginas no ficheiro combinado sem marcas de página no corpo.
_PAGE_JOIN = "\n\n"


@dataclass(frozen=True)
class PageRecord:
    """Uma página extraída (1-based ``page``) e texto markdown limpo."""

    page: int
    markdown: str


def clean_markdown(text: str) -> str:
    """
    Reduz ruído repetido (rodapés, números de página isolados) sem alterar conteúdo clínico.
    Heurísticas conservadoras; ajustar após inspecionar PDFs reais.
    """
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Linha só com número (possível número de página isolado).
        if re.fullmatch(r"\d{1,4}", stripped):
            continue
        out.append(line)
    result = "\n".join(out)
    # Normaliza quebras finais.
    return result.strip() + ("\n" if result.strip() else "")


def _chunks_from_pymupdf(pdf_path: Path) -> list[PageRecord]:
    """Chama pymupdf4llm com page_chunks e devolve registos por página."""
    raw = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)
    if not isinstance(raw, list):
        raise TypeError(f"esperado list com page_chunks=True, obtido {type(raw)}")

    records: list[PageRecord] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if text is None:
            continue
        meta = item.get("metadata") or {}
        page_num = meta.get("page_number")
        if page_num is None:
            continue
        cleaned = clean_markdown(str(text))
        records.append(PageRecord(page=int(page_num), markdown=cleaned))
    records.sort(key=lambda r: r.page)
    return records


def combined_markdown_from_pages(pages: list[PageRecord]) -> str:
    """Concatena páginas na ordem com ``\\n\\n`` entre páginas."""
    parts = [p.markdown for p in pages if p.markdown.strip()]
    return _PAGE_JOIN.join(parts) + ("\n" if parts else "")


def write_pages_jsonl(pages: list[PageRecord], path: Path) -> None:
    """Grava uma linha JSON por página: page, markdown."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in pages:
            line = json.dumps(
                {"page": rec.page, "markdown": rec.markdown},
                ensure_ascii=False,
            )
            f.write(line + "\n")


def read_pages_jsonl(path: Path) -> list[PageRecord]:
    """Lê o sidecar gerado por ``write_pages_jsonl``."""
    pages: list[PageRecord] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj: dict[str, Any] = json.loads(line)
            pages.append(
                PageRecord(
                    page=int(obj["page"]),
                    markdown=str(obj.get("markdown", "")),
                )
            )
    pages.sort(key=lambda p: p.page)
    return pages


def sha256_file(path: Path) -> str:
    """Hash SHA-256 do ficheiro."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def relative_to_data_root(path: Path, base: Path) -> str:
    """Caminho POSIX relativo a ``base``."""
    return path.resolve().relative_to(base.resolve()).as_posix()


def extract_one_pdf(
    pdf_path: Path,
    *,
    processed_dir: Path,
    data_base: Path,
    with_combined_md: bool,
    force: bool,
) -> dict[str, Any]:
    """
    Extrai um PDF: grava sempre ``<stem>.pages.jsonl``; grava ``<stem>.md`` só se
    ``with_combined_md`` for True.

    Retorna um dicionário de linha de manifesto (relativos a ``data_base``).
    """
    # --- Caminhos de saída e metadados comuns ao manifesto ---
    stem = pdf_path.stem
    pages_jsonl = processed_dir / f"{stem}{PAGE_JSONL_SUFFIX}"
    md_path = processed_dir / f"{stem}.md"
    pdf_rel = relative_to_data_root(pdf_path, data_base)
    jsonl_rel = relative_to_data_root(pages_jsonl, data_base)
    md_rel: str | None = relative_to_data_root(md_path, data_base) if with_combined_md else None

    ts = now_iso()

    if not pdf_path.is_file():
        return {
            "pdf_relative_path": pdf_rel,
            "pages_jsonl_relative_path": jsonl_rel,
            "md_relative_path": None,
            "wrote_combined_md": False,
            "status": "error",
            "error": "ficheiro PDF inexistente",
            "sha256": None,
            "extracted_at": ts,
        }

    pdf_mtime = pdf_path.stat().st_mtime
    sidecar_ok = pages_jsonl.is_file() and pages_jsonl.stat().st_mtime >= pdf_mtime

    # --- Sidecar atualizado: não reler o PDF salvo com --force ---
    if not force and sidecar_ok:
        if with_combined_md:
            md_missing = not md_path.is_file()
            md_stale = (
                md_path.is_file()
                and md_path.stat().st_mtime < pages_jsonl.stat().st_mtime
            )
            md_fresh = md_path.is_file() and not md_missing and not md_stale
            if md_fresh:
                return {
                    "pdf_relative_path": pdf_rel,
                    "pages_jsonl_relative_path": jsonl_rel,
                    "md_relative_path": md_rel,
                    "wrote_combined_md": False,
                    "status": "skipped",
                    "error": None,
                    "sha256": sha256_file(pdf_path),
                    "extracted_at": ts,
                }
            if md_missing or md_stale:
                # Reconstrói só o .md a partir do sidecar (sem reler o PDF).
                try:
                    pages = read_pages_jsonl(pages_jsonl)
                    combined = combined_markdown_from_pages(pages)
                    md_path.write_text(combined, encoding="utf-8")
                except OSError as e:
                    return {
                        "pdf_relative_path": pdf_rel,
                        "pages_jsonl_relative_path": jsonl_rel,
                        "md_relative_path": md_rel,
                        "wrote_combined_md": False,
                        "status": "error",
                        "error": str(e),
                        "sha256": sha256_file(pdf_path),
                        "extracted_at": ts,
                    }
                return {
                    "pdf_relative_path": pdf_rel,
                    "pages_jsonl_relative_path": jsonl_rel,
                    "md_relative_path": md_rel,
                    "wrote_combined_md": True,
                    "status": "ok",
                    "error": None,
                    "sha256": sha256_file(pdf_path),
                    "extracted_at": ts,
                }
        else:
            return {
                "pdf_relative_path": pdf_rel,
                "pages_jsonl_relative_path": jsonl_rel,
                "md_relative_path": None,
                "wrote_combined_md": False,
                "status": "skipped",
                "error": None,
                "sha256": sha256_file(pdf_path),
                "extracted_at": ts,
            }

    # --- pymupdf4llm: nova extração ou reextração forçada ---
    try:
        pages = _chunks_from_pymupdf(pdf_path)
    except Exception as e:
        _log.exception("Falha ao extrair %s", pdf_path)
        return {
            "pdf_relative_path": pdf_rel,
            "pages_jsonl_relative_path": jsonl_rel,
            "md_relative_path": None,
            "wrote_combined_md": False,
            "status": "error",
            "error": str(e),
            "sha256": sha256_file(pdf_path) if pdf_path.is_file() else None,
            "extracted_at": ts,
        }

    try:
        write_pages_jsonl(pages, pages_jsonl)
        wrote_md = False
        if with_combined_md:
            combined = combined_markdown_from_pages(pages)
            md_path.write_text(combined, encoding="utf-8")
            wrote_md = True
    except OSError as e:
        return {
            "pdf_relative_path": pdf_rel,
            "pages_jsonl_relative_path": jsonl_rel,
            "md_relative_path": md_rel if with_combined_md else None,
            "wrote_combined_md": False,
            "status": "error",
            "error": str(e),
            "sha256": sha256_file(pdf_path),
            "extracted_at": ts,
        }

    return {
        "pdf_relative_path": pdf_rel,
        "pages_jsonl_relative_path": jsonl_rel,
        "md_relative_path": md_rel if wrote_md else None,
        "wrote_combined_md": wrote_md,
        "status": "ok",
        "error": None,
        "sha256": sha256_file(pdf_path),
        "extracted_at": ts,
    }


def default_processed_dir() -> Path:
    """Diretório processado PCDT sob ``llm/data``."""
    return data_root() / DIR_PROCESSED_PCDT
