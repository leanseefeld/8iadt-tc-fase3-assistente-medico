"""Cliente HTTP (httpx) para ingestão PCDT."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class HttpxFetcher:
    """Obtém HTML e bytes via httpx."""

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


def normalize_link(base_url: str, href: str) -> str | None:
    """Resolve href contra base_url; retorna URL http(s) sem fragmento ou None."""
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return None
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
        return None
    return absolute.split("#", 1)[0]
