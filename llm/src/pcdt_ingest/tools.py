"""Ferramentas LangChain (`@tool`) — wrappers finos sobre funções puras."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

from langchain_core.tools import tool

from pcdt_ingest.http_client import extract_links, is_probably_pdf_url


def _slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name or "document"
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)[:180]
    return name or "document.pdf"


def local_filename(source_url: str, content_type: str | None) -> str:
    """Sugere nome de arquivo local (uso direto no grafo, sem `.invoke`)."""
    base = _slug_from_url(source_url)
    if not base.lower().endswith(".pdf") and content_type and "pdf" in content_type.lower():
        if "." not in base:
            base = f"{base}.pdf"
    if not is_probably_pdf_url(source_url) and not base.lower().endswith(".pdf"):
        base = f"{base}.bin"
    return base


@tool
def compute_sha256_bytes(data: bytes) -> str:
    """Calcula SHA-256 de bytes."""
    return hashlib.sha256(data).hexdigest()


@tool
def parse_html_for_pcdt_links(html: str, base_url: str) -> dict:
    """
    Extrai links PDF e páginas HTML candidatas no domínio gov.br.
    Retorna chaves `pdf_urls` e `html_urls`.
    """
    pdfs, pages = extract_links(html, base_url)
    return {"pdf_urls": pdfs, "html_urls": pages}


@tool
def suggest_local_filename(source_url: str, content_type: str | None = None) -> str:
    """Sugere nome de arquivo local a partir da URL e opcionalmente do Content-Type."""
    return local_filename(source_url, content_type)
