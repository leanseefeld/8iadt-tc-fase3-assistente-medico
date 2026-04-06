"""Filtros de URL para restringir crawl e downloads ao escopo PCDT (CONITEC)."""

from __future__ import annotations

from urllib.parse import urlparse

# Marcadores no caminho/query típicos de PCDT e páginas da mesma seção.
_PCDT_MARKERS = (
    "protocolos-clinicos-e-diretrizes-terapeuticas",
    "protocolos-clinicos",
    "diretrizes-terapeuticas",
    "protocolo-clinico",
    "/pcdt/",
    "pcdt/",  # início de segmento
)


def pcdt_listing_prefix(seed_url: str) -> str:
    """
    Prefixo de URL usado para limitar o crawl a páginas filhas da listagem PCDT.

    Se a semente contiver o segmento oficial da página PCDT, o prefixo inclui esse
    segmento (sem exigir subpaths adicionais). Caso contrário, usa a própria semente.
    """
    u = seed_url.strip().split("#", 1)[0].rstrip("/")
    low = u.lower()
    marker = "protocolos-clinicos-e-diretrizes-terapeuticas"
    if marker in low:
        end = low.index(marker) + len(marker)
        return u[:end]
    return u


def _lower_path_and_query(url: str) -> str:
    p = urlparse(url)
    return f"{p.path.lower()}?{p.query.lower()}"


def url_matches_pcdt_markers(url: str) -> bool:
    """Indica se a URL parece ligada a PCDT por segmentos de caminho ou consulta."""
    hay = _lower_path_and_query(url)
    return any(m in hay for m in _PCDT_MARKERS)


def url_under_listing_prefix(url: str, seed_url: str) -> bool:
    """True se a URL compartilha o prefixo da listagem PCDT (mesma árvore da semente)."""
    prefix = pcdt_listing_prefix(seed_url).rstrip("/")
    cand = url.split("#", 1)[0].rstrip("/")
    return cand.lower().startswith(prefix.lower())


def is_pcdt_pdf_url(url: str, seed_url: str) -> bool:
    """
    Mantém PDFs claramente ligados a PCDT: marcadores no path/query OU sob o prefixo
    da semente (ex.: versões HTML/PDF na mesma pasta da listagem).
    """
    return url_matches_pcdt_markers(url) or url_under_listing_prefix(url, seed_url)


def is_pcdt_candidate_pdf_url(url: str) -> bool:
    """
    PDFs típicos distribuídos pelo fluxo CONITEC/MS.

    A maior parte dos arquivos fica em ``/conitec/.../midias/...``, **fora** do prefixo
    textual da página de listagem — por isso exigir só ``url_under_listing_prefix`` ou
    marcadores no nome eliminava quase todos os links.

    Regras (uma basta):
    - path contém ``/conitec/``;
    - ou marcadores PCDT no path/query;
    - ou host ``saude.gov.br`` (anexos ofticiais citados nos protocolos).
    """
    from pcdt_ingest.http_client import is_probably_pdf_url, is_same_site_gov_br

    if not is_probably_pdf_url(url) or not is_same_site_gov_br(url):
        return False
    low = url.lower()
    if "/conitec/" in low:
        return True
    if url_matches_pcdt_markers(url):
        return True
    host = urlparse(url).netloc.lower()
    if host.endswith("saude.gov.br"):
        return True
    return False


def is_pcdt_crawl_html_url(url: str, seed_url: str) -> bool:
    """
    Páginas HTML a enfileirar no modo estrito.

    - Filhas diretas da listagem (mesmo prefixo da semente).
    - Ou ramo ``avaliacao-de-tecnologias-em-saude`` com segmento explícito PCDT
      (evita notícias genéricas sob ``/assuntos/``).
    """
    path = urlparse(url).path.lower()
    if "/conitec/" not in path:
        return False
    if url_under_listing_prefix(url, seed_url):
        return True
    ats = "avaliacao-de-tecnologias-em-saude"
    if ats in path and (
        "protocolos-clinicos-e-diretrizes-terapeuticas" in path
        or "/pcdt/" in path
        or path.rstrip("/").endswith("/pcdt")
    ):
        return True
    return False
