"""Download do conjunto Einstein (USP Data Sharing / handle item 98)."""

from __future__ import annotations

import hashlib
import re
import warnings
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from pcdt_ingest.http_client import DEFAULT_USER_AGENT
from pcdt_ingest.manifest import now_iso, write_json, write_jsonl
from pcdt_ingest.paths import ensure_data_dirs

DEFAULT_HANDLE_URL = (
    "https://repositoriodatasharingfapesp.uspdigital.usp.br/handle/item/98"
)

_ASSET_SUFFIX = re.compile(
    r"\.(csv|xlsx|xls|zip|pdf|txt)$",
    re.IGNORECASE,
)


def _same_repository(url: str, base: str) -> bool:
    return urlparse(url).netloc.lower() == urlparse(base).netloc.lower()


def discover_bitstream_urls(html: str, base_url: str) -> list[tuple[str, str]]:
    """Retorna lista de (url_absoluta, rótulo de texto do link)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "lxml")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith("#"):
            continue
        abs_url = urljoin(base_url, href)
        if not _same_repository(abs_url, base_url):
            continue
        low = abs_url.lower()
        if "bitstream" in low or _ASSET_SUFFIX.search(low):
            if abs_url not in seen:
                seen.add(abs_url)
                label = tag.get_text(" ", strip=True) or Path(urlparse(abs_url).path).name
                out.append((abs_url, label))
    return out


def download_clinical_exams_bundle(
    *,
    handle_url: str = DEFAULT_HANDLE_URL,
    timeout_s: float = 120.0,
) -> list[dict]:
    """
    Baixa arquivos publicados na página do handle e grava em `llm/data/raw/clinical_exams/`.
    Retorna linhas do manifesto.
    """
    base = ensure_data_dirs()
    raw_dir = base / "raw" / "clinical_exams"
    raw_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Language": "pt-BR,pt;q=0.9",
    }
    rows: list[dict] = []

    with httpx.Client(headers=headers, timeout=timeout_s, follow_redirects=True) as client:
        r = client.get(handle_url)
        r.raise_for_status()
        links = discover_bitstream_urls(r.text, str(r.url))

        for url, title in links:
            try:
                resp = client.get(url)
                status = resp.status_code
                if status >= 400:
                    rows.append(
                        {
                            "id": hashlib.sha256(url.encode()).hexdigest()[:16],
                            "source_url": url,
                            "title": title,
                            "fetched_at": now_iso(),
                            "bytes": 0,
                            "sha256": "",
                            "relative_path": "",
                            "status": "error",
                            "detail": f"HTTP {status}",
                        }
                    )
                    continue
                data = resp.content
                ctype = (resp.headers.get("content-type") or "").lower()
                if "text/html" in ctype or data.lstrip()[:1] == b"<":
                    rows.append(
                        {
                            "id": hashlib.sha256(url.encode()).hexdigest()[:16],
                            "source_url": url,
                            "title": title,
                            "fetched_at": now_iso(),
                            "bytes": len(data),
                            "sha256": "",
                            "relative_path": "",
                            "status": "error",
                            "detail": "Resposta HTML (ex.: termos de uso); conclua o aceite no navegador e baixe manualmente ou use sessão autenticada.",
                        }
                    )
                    continue
                sha = hashlib.sha256(data).hexdigest()
                name = Path(urlparse(url).path).name or f"file_{sha[:8]}"
                name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)[:200]
                out_path = raw_dir / name
                out_path.write_bytes(data)
                rel = Path("raw/clinical_exams") / name
                rows.append(
                    {
                        "id": hashlib.sha256(url.encode()).hexdigest()[:16],
                        "source_url": url,
                        "title": title,
                        "fetched_at": now_iso(),
                        "bytes": len(data),
                        "sha256": sha,
                        "relative_path": str(rel).replace("\\", "/"),
                        "status": "ok",
                    }
                )
            except Exception as e:  # noqa: BLE001
                rows.append(
                    {
                        "id": hashlib.sha256(url.encode()).hexdigest()[:16],
                        "source_url": url,
                        "title": title,
                        "fetched_at": now_iso(),
                        "bytes": 0,
                        "sha256": "",
                        "relative_path": "",
                        "status": "error",
                        "detail": str(e),
                    }
                )

    manifests = base / "manifests"
    write_jsonl(manifests / "clinical_exams_index.jsonl", rows)
    write_json(
        manifests / "clinical_exams_run.json",
        {
            "run_at": now_iso(),
            "handle_url": handle_url,
            "counts": {
                "ok": sum(1 for x in rows if x.get("status") == "ok"),
                "error": sum(1 for x in rows if x.get("status") == "error"),
            },
        },
    )
    return rows
