"""Download linear de PCDT: uma página de listagem, tabela CONITEC, sem crawl."""

from __future__ import annotations

import hashlib
import re
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

from pcdt_ingest.http_client import DEFAULT_USER_AGENT, HttpxFetcher, normalize_link
from pcdt_ingest.logutil import get_logger
from pcdt_ingest.manifest import append_jsonl_line, now_iso, write_json
from pcdt_ingest.paths import (
    DIR_MANIFESTS,
    DIR_RAW_PCDT,
    MANIFEST_PCDT_INDEX,
    MANIFEST_PCDT_RUN,
    ensure_data_dirs,
)

_log = get_logger("pcdt_download")

# Texto do título da seção na página oficial CONITEC (listagem PCDT).
PCDT_SECTION_TITLE = "Protocolos Clínicos e Diretrizes Terapêuticas - PCDT"

SCRIPT_VERSION = "0.2.0"


def _normalize_visible_text(text: str) -> str:
    return " ".join(text.split())


def _text_after_anchor(anchor: Tag) -> str:
    """
    Texto visível dos nós irmãos que seguem o ``<a>`` no mesmo pai
    (trecho tipicamente com portaria e datas, sem repetir o título do link).
    """
    parts: list[str] = []
    for sib in anchor.next_siblings:
        if isinstance(sib, NavigableString):
            chunk = str(sib).strip()
            if chunk:
                parts.append(chunk)
        elif isinstance(sib, Tag):
            chunk = sib.get_text(separator=" ", strip=True)
            if chunk:
                parts.append(chunk)
    return _normalize_visible_text(" ".join(parts))


def _has_class(tag: Any, name: str) -> bool:
    classes = tag.get("class")
    if not classes:
        return False
    if isinstance(classes, str):
        return classes == name
    return name in classes


def _doc_id_from_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _slug_from_url_path(url: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name or "document"
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)[:180]
    return name or "document"


def local_filename(source_url: str, content_type: str | None) -> str:
    """Nome de arquivo local a partir da URL e do Content-Type da resposta."""
    base = _slug_from_url_path(source_url)
    low_ct = (content_type or "").lower()
    low_base = base.lower()
    if "pdf" in low_ct:
        return base if low_base.endswith(".pdf") else f"{base}.pdf"
    if low_base.endswith(".pdf"):
        return base
    if "html" in low_ct:
        return base if "." in base else f"{base}.html"
    return base if "." in base else f"{base}.bin"


def parse_pcdt_table_links(html: str, base_url: str) -> list[tuple[str, str, str]]:
    """
    Extrai entradas da tabela PCDT: (título do link, url absoluta, texto após o link na célula).

    O terceiro elemento junta texto e subárvores irmãs posteriores ao ``<a>`` na segunda coluna
    (ex.: portaria e datas), sem incluir o próprio texto do link.

    Localiza o bloco ``#content-core > .item`` a partir do headline/h2 da seção,
    depois a primeira ``table``; em cada ``tr`` usa só a segunda ``td`` e links ``a``.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "lxml")

    heading = None
    for tag in soup.select("h2, .headline"):
        if PCDT_SECTION_TITLE in _normalize_visible_text(tag.get_text()):
            heading = tag
            break

    if heading is None:
        msg = (
            f"Não foi encontrado título da seção ({PCDT_SECTION_TITLE!r}) "
            "em elemento .headline ou h2."
        )
        raise ValueError(msg)

    item_block = None
    cur: Any = heading
    while cur is not None:
        parent = cur.parent
        if parent is not None and parent.get("id") == "content-core":
            if _has_class(cur, "item"):
                item_block = cur
                break
        cur = parent

    if item_block is None:
        raise ValueError("Não foi encontrado ancestral #content-core > .item a partir do título.")

    table = item_block.find("table")
    if table is None:
        raise ValueError("Nenhuma <table> encontrada dentro do bloco .item.")

    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for cell in table.select("tr > td:nth-of-type(2)"):
        a = cell.find("a", href=True)
        if not a:
            continue
        href = a.get("href")
        if not href or not isinstance(href, str):
            continue
        abs_url = normalize_link(base_url, href.strip())
        if not abs_url:
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        title = _normalize_visible_text(a.get_text())
        source_description = _text_after_anchor(a)
        out.append((title, abs_url, source_description))

    return out


def _write_run_summary(
    *,
    manifests_dir: Path,
    listing_url: str,
    links_discovered: int,
    ok_count: int,
    skipped_count: int,
    error_count: int,
    errors: list[str],
    run_started_at: str,
) -> None:
    summary = {
        "run_started_at": run_started_at,
        "last_updated_at": now_iso(),
        "script_version": SCRIPT_VERSION,
        "listing_url": listing_url,
        "links_discovered": links_discovered,
        "counts": {
            "ok": ok_count,
            "skipped": skipped_count,
            "error": error_count,
        },
        "errors": errors,
    }
    write_json(manifests_dir / MANIFEST_PCDT_RUN, summary)


def run_pcdt_download(
    *,
    listing_url: str,
    max_files: int,
    timeout_s: float,
    user_agent: str = "",
) -> dict[str, Any]:
    """
    Baixa documentos cujos links aparecem na tabela da página de listagem.

    Acrescenta uma linha em ``pcdt_index.jsonl`` e regrava ``pcdt_run.json`` após cada tentativa.
    """
    # --- Caminhos sob llm/data e acumuladores do run ---
    base = ensure_data_dirs()
    raw_dir = base / DIR_RAW_PCDT
    manifests_dir = base / DIR_MANIFESTS
    pcdt_index_path = manifests_dir / MANIFEST_PCDT_INDEX

    ua = user_agent.strip() or DEFAULT_USER_AGENT
    run_started_at = now_iso()
    errors: list[str] = []
    entries: list[dict[str, Any]] = []

    # --- Novo run: esvazia o índice JSONL (append linha a linha depois) ---
    pcdt_index_path.write_text("", encoding="utf-8")

    fetcher = HttpxFetcher(user_agent=ua, timeout_s=timeout_s)
    try:
        # --- 1) GET da página de listagem (HTML com a tabela PCDT) ---
        status, html, _ctype = fetcher.get_html(listing_url)
        if status >= 400 or not html:
            msg = f"HTTP {status} ao buscar listagem {listing_url}"
            errors.append(msg)
            _write_run_summary(
                manifests_dir=manifests_dir,
                listing_url=listing_url,
                links_discovered=0,
                ok_count=0,
                skipped_count=0,
                error_count=0,
                errors=errors,
                run_started_at=run_started_at,
            )
            return {"download_entries": entries, "errors": errors}

        # --- 2) Parse do DOM: (título, url, source_description) por linha ---
        try:
            pairs = parse_pcdt_table_links(html, listing_url)
        except ValueError as e:
            errors.append(str(e))
            _write_run_summary(
                manifests_dir=manifests_dir,
                listing_url=listing_url,
                links_discovered=0,
                ok_count=0,
                skipped_count=0,
                error_count=0,
                errors=errors,
                run_started_at=run_started_at,
            )
            return {"download_entries": entries, "errors": errors}

        # --- 3) Fila de downloads: total na página vs. limite --max-files ---
        links_discovered = len(pairs)
        pairs = pairs[:max_files]
        seen_hashes: set[str] = set()
        used_names: set[str] = set()
        ok_count = skipped_count = error_count = 0

        # --- 4) Por URL: GET bytes → registro de manifesto → flush JSONL + pcdt_run.json ---
        for i, (doc_title, url, source_description) in enumerate(pairs, start=1):
            _log.info("[%d/%d] GET %s", i, len(pairs), url)
            desc_val = source_description or None
            row: dict[str, Any]
            try:
                st, data, ctype = fetcher.get_bytes(url)
                # Falha se status HTTP >= 400
                if st >= 400:
                    detail = f"HTTP {st}"
                    errors.append(f"{url}: {detail}")
                    row = {
                        "id": _doc_id_from_url(url),
                        "source_url": url,
                        "title": doc_title or None,
                        "source_description": desc_val,
                        "fetched_at": now_iso(),
                        "content_type": ctype,
                        "bytes": 0,
                        "sha256": "",
                        "relative_path": "",
                        "status": "error",
                        "detail": detail,
                    }
                    error_count += 1
                else:
                    sha = hashlib.sha256(data).hexdigest()
                    # Mesmo PDF já baixado nesta execução (dedup por SHA-256)
                    if sha in seen_hashes:
                        row = {
                            "id": _doc_id_from_url(url),
                            "source_url": url,
                            "title": doc_title or None,
                            "source_description": desc_val,
                            "fetched_at": now_iso(),
                            "content_type": ctype,
                            "bytes": len(data),
                            "sha256": sha,
                            "relative_path": "",
                            "status": "skipped",
                            "detail": "duplicate_sha256",
                        }
                        skipped_count += 1
                    else:
                        # Grava em raw/pcdt e monta linha status=ok
                        seen_hashes.add(sha)
                        name = local_filename(url, ctype)
                        if name in used_names:
                            stem = Path(name).stem
                            suffix = Path(name).suffix or ".bin"
                            name = f"{stem}_{sha[:8]}{suffix}"
                        used_names.add(name)

                        rel = DIR_RAW_PCDT / name
                        out_path = raw_dir / name
                        out_path.write_bytes(data)

                        row = {
                            "id": _doc_id_from_url(url),
                            "source_url": url,
                            "title": doc_title or None,
                            "source_description": desc_val,
                            "fetched_at": now_iso(),
                            "content_type": ctype,
                            "bytes": len(data),
                            "sha256": sha,
                            "relative_path": rel.as_posix(),
                            "status": "ok",
                        }
                        ok_count += 1
                        _log.info("Salvo %s (%d bytes)", rel, len(data))
            except Exception as e:  # noqa: BLE001
                errors.append(f"Download falhou {url}: {e!s}")
                row = {
                    "id": _doc_id_from_url(url),
                    "source_url": url,
                    "title": doc_title or None,
                    "source_description": desc_val,
                    "fetched_at": now_iso(),
                    "content_type": None,
                    "bytes": 0,
                    "sha256": "",
                    "relative_path": "",
                    "status": "error",
                    "detail": str(e),
                }
                error_count += 1

            # --- Após cada tentativa: memória + uma linha no JSONL + resumo do run ---
            entries.append(row)
            append_jsonl_line(pcdt_index_path, row)
            _write_run_summary(
                manifests_dir=manifests_dir,
                listing_url=listing_url,
                links_discovered=links_discovered,
                ok_count=ok_count,
                skipped_count=skipped_count,
                error_count=error_count,
                errors=errors,
                run_started_at=run_started_at,
            )
    finally:
        # --- Fecha cliente HTTP (também em retornos antecipados após o GET da listagem) ---
        fetcher.close()

    return {"download_entries": entries, "errors": errors}
