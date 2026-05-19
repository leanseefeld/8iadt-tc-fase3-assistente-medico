"""Limpeza estruturada de sidecars PCDT ``*.pages.jsonl``."""

from pcdt_ingest.clean.cleaner import clean_pages, clean_pages_jsonl
from pcdt_ingest.clean.heuristics import (
    classify_document,
    find_clinical_content_start_page,
    is_junk_text,
)
from pcdt_ingest.clean.models import (
    CleanConfig,
    CleanStats,
    DocumentClass,
    PageCleanResult,
)

__all__ = [
    "CleanConfig",
    "CleanStats",
    "DocumentClass",
    "PageCleanResult",
    "clean_pages",
    "clean_pages_jsonl",
    "classify_document",
    "find_clinical_content_start_page",
    "is_junk_text",
]