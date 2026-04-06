"""Estado do grafo LangGraph para ingestão PCDT."""

from __future__ import annotations

from typing import Any, TypedDict


class PCDTIngestState(TypedDict, total=False):
    """Estado compartilhado entre nós do grafo (mesclagem por chave)."""

    # Entrada / config
    listing_seed_url: str
    output_root: str
    max_pages: int
    max_files: int
    user_agent: str
    request_timeout_s: float
    follow_internal_html: bool
    conitec_path_hint: str
    strict_pcdt_only: bool

    # Rastreamento de páginas HTML
    pending_pages: list[str]
    fetched_pages: list[str]
    current_html: str | None
    current_fetch_url: str | None

    # PDFs descobertos (lista única; nós devolvem lista completa atualizada)
    pdf_urls: list[str]

    # Resultado de downloads
    download_entries: list[dict[str, Any]]
    errors: list[str]

    # Controle do laço de descoberta
    discovery_done: bool
