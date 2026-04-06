"""Cliente HTTP com User-Agent e opção Playwright para HTML."""

from __future__ import annotations

import re
import time
import warnings
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import XMLParsedAsHTMLWarning

from pcdt_ingest.logutil import get_logger

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class HTMLFetcher(Protocol):
    def get_html(self, url: str) -> tuple[int, str, str | None]:
        """Retorna (status_code, text, content_type)."""


class HttpxFetcher:
    """Obtém HTML via httpx."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_s: float = 60.0,
    ) -> None:
        headers = {"User-Agent": user_agent, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}
        self._client = httpx.Client(
            headers=headers,
            timeout=timeout_s,
            follow_redirects=True,
        )

    def get_html(self, url: str) -> tuple[int, str, str | None]:
        r = self._client.get(url)
        ctype = r.headers.get("content-type")
        return r.status_code, r.text, ctype

    def get_bytes(self, url: str) -> tuple[int, bytes, str | None]:
        r = self._client.get(url)
        return r.status_code, r.content, r.headers.get("content-type")

    def close(self) -> None:
        self._client.close()


class PlaywrightFetcher:
    """Fallback: renderiza página com Chromium (JS)."""

    _log = get_logger("playwright")

    def __init__(
        self,
        user_agent: str | None = None,
        timeout_ms: int = 60_000,
    ) -> None:
        self._user_agent = user_agent or DEFAULT_USER_AGENT
        self._timeout_ms = timeout_ms

    def get_html(self, url: str) -> tuple[int, str, str | None]:
        from playwright.sync_api import sync_playwright

        self._log.info(
            "Playwright: iniciando (timeout=%d ms). A primeira execução pode demorar (download do Chromium).",
            self._timeout_ms,
        )
        t0 = time.perf_counter()
        with sync_playwright() as p:
            self._log.info("Playwright: iniciando browser Chromium (headless)…")
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(user_agent=self._user_agent, locale="pt-BR")
                page = ctx.new_page()
                self._log.info(
                    "Playwright: abrindo %s (wait_until=networkidle — pode travar em páginas com WebSocket/polling longo).",
                    url[:120] + ("…" if len(url) > 120 else ""),
                )
                resp = page.goto(url, wait_until="networkidle", timeout=self._timeout_ms)
                status = resp.status if resp else 0
                self._log.info(
                    "Playwright: navegação concluída (status=%s, %.1f s). Extraindo HTML…",
                    status,
                    time.perf_counter() - t0,
                )
                html = page.content()
                self._log.info(
                    "Playwright: HTML obtido (%d caracteres, %.1f s no total).",
                    len(html),
                    time.perf_counter() - t0,
                )
                return status, html, "text/html"
            finally:
                browser.close()
                self._log.info(
                    "Playwright: browser encerrado (%.1f s).",
                    time.perf_counter() - t0,
                )


def is_same_site_gov_br(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith("gov.br")


def is_probably_pdf_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or "/pdf" in path or "format=pdf" in url.lower()


def normalize_link(base_url: str, href: str) -> str | None:
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return None
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
        return None
    # Remove fragment
    clean = absolute.split("#", 1)[0]
    return clean


def conitec_html_neighbor(url: str, path_hint: str) -> bool:
    """Indica se o caminho parece página de conteúdo CONITEC (não assets globais)."""
    path = urlparse(url).path.lower()
    hint = path_hint.strip("/").lower()
    return hint in path or "pcdt" in path or "protocolo" in path


_WS_RE = re.compile(r"\s+")


def extract_links(html: str, base_url: str) -> tuple[list[str], list[str]]:
    """
    Retorna (urls_pdf, urls_html) absolutas a partir do HTML.
    """
    from bs4 import BeautifulSoup

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "lxml")
    pdfs: list[str] = []
    html_pages: list[str] = []
    seen: set[str] = set()

    for tag in soup.find_all("a", href=True):
        raw = tag.get("href")
        if not raw or not isinstance(raw, str):
            continue
        norm = normalize_link(base_url, raw.strip())
        if not norm or norm in seen:
            continue
        if not is_same_site_gov_br(norm):
            continue
        seen.add(norm)
        if is_probably_pdf_url(norm):
            pdfs.append(norm)
        elif norm.endswith(".html") or "/pt-br/" in norm or "/conitec/" in norm:
            html_pages.append(norm)

    return pdfs, html_pages
