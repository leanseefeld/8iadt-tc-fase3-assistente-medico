"""Grafo LangGraph: descoberta de PDFs CONITEC e download."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from langgraph.graph import END, StateGraph

from pcdt_ingest.http_client import (
    DEFAULT_USER_AGENT,
    HttpxFetcher,
    PlaywrightFetcher,
    conitec_html_neighbor,
    extract_links,
)
from pcdt_ingest.logutil import get_logger
from pcdt_ingest.pcdt_filters import is_pcdt_candidate_pdf_url, is_pcdt_crawl_html_url
from pcdt_ingest.manifest import now_iso, write_json, write_jsonl
from pcdt_ingest.paths import ensure_data_dirs
from pcdt_ingest.state import PCDTIngestState
from pcdt_ingest.tools import local_filename

_log = get_logger("graph")


def _merge_unique(base: list[str], extra: list[str]) -> list[str]:
    seen = set(base)
    out = list(base)
    for u in extra:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _doc_id_from_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def node_init(state: PCDTIngestState) -> dict[str, Any]:
    """Inicializa filas a partir da URL semente."""
    _log.info("Nó [init]: fila semente = %s", state.get("listing_seed_url", ""))
    return {
        "pending_pages": [state["listing_seed_url"]],
        "fetched_pages": [],
        "pdf_urls": [],
        "download_entries": [],
        "errors": [],
        "discovery_done": False,
        "current_html": None,
        "current_fetch_url": None,
    }


def _fetcher_for_state(state: PCDTIngestState, use_playwright: bool):
    ua = (state.get("user_agent") or "").strip()
    timeout = float(state.get("request_timeout_s") or 60.0)
    if use_playwright:
        return PlaywrightFetcher(
            user_agent=ua or None,
            timeout_ms=int(timeout * 1000),
        )
    return HttpxFetcher(user_agent=ua or DEFAULT_USER_AGENT, timeout_s=timeout)


def build_fetch_one(use_playwright: bool):
    """Factory do nó que busca uma página HTML e extrai links."""

    def fetch_one(state: PCDTIngestState) -> dict[str, Any]:
        max_pages = int(state.get("max_pages") or 30)
        pending = list(state.get("pending_pages") or [])
        fetched = list(state.get("fetched_pages") or [])
        pdf_urls = list(state.get("pdf_urls") or [])
        errors = list(state.get("errors") or [])
        follow = bool(state.get("follow_internal_html", True))
        hint = state.get("conitec_path_hint") or "conitec"

        if len(fetched) >= max_pages or not pending:
            _log.info(
                "Nó [fetch_one]: fase de descoberta encerrada (páginas buscadas=%d/%d, fila vazia=%s).",
                len(fetched),
                max_pages,
                not pending,
            )
            return {"discovery_done": True}

        url = pending[0]
        rest = pending[1:]

        mode = "playwright" if use_playwright else "httpx"
        _log.info(
            "Nó [fetch_one]: buscando página %d/%d via %s (%d na fila, %d PDFs já listados)…",
            len(fetched) + 1,
            max_pages,
            mode,
            len(pending),
            len(pdf_urls),
        )
        _log.info("Nó [fetch_one]: URL = %s", url)

        fetcher = _fetcher_for_state(state, use_playwright)
        try:
            status, html, ctype = fetcher.get_html(url)
            if isinstance(fetcher, HttpxFetcher):
                fetcher.close()
            if status >= 400 or not html:
                _log.warning("Nó [fetch_one]: falha HTTP %s para %s", status, url)
                errors.append(f"HTTP {status} ao buscar {url}")
                nf = len(fetched) + 1
                done = nf >= max_pages or not rest
                return {
                    "pending_pages": rest,
                    "fetched_pages": fetched + [url],
                    "errors": errors,
                    "discovery_done": done,
                }
        except Exception as e:  # noqa: BLE001
            if isinstance(fetcher, HttpxFetcher):
                fetcher.close()
            _log.exception("Nó [fetch_one]: exceção ao buscar %s", url)
            errors.append(f"Erro ao buscar {url}: {e!s}")
            nf = len(fetched) + 1
            done = nf >= max_pages or not rest
            return {
                "pending_pages": rest,
                "fetched_pages": fetched + [url],
                "errors": errors,
                "discovery_done": done,
            }

        pdfs_raw, html_pages = extract_links(html, url)
        seed = state.get("listing_seed_url") or ""
        strict = bool(state.get("strict_pcdt_only", True))

        if strict:
            pdfs = [u for u in pdfs_raw if is_pcdt_candidate_pdf_url(u)]
            dropped = len(pdfs_raw) - len(pdfs)
            if dropped:
                _log.info(
                    "Nó [fetch_one]: filtro PCDT excluiu %d links PDF desta página (%d mantidos).",
                    dropped,
                    len(pdfs),
                )
        else:
            pdfs = pdfs_raw

        pdf_urls = _merge_unique(pdf_urls, pdfs)

        _log.info(
            "Nó [fetch_one]: links PDF: %d brutos → %d aceitos; páginas HTML: %d (follow=%s, escopo=%s).",
            len(pdfs_raw),
            len(pdfs),
            len(html_pages),
            follow,
            "PCDT" if strict else "CONITEC ampliado",
        )

        new_pending = list(rest)
        if follow:
            for p in html_pages:
                if p in fetched or p == url:
                    continue
                if strict:
                    if not is_pcdt_crawl_html_url(p, seed):
                        continue
                elif not conitec_html_neighbor(p, hint):
                    continue
                if p not in new_pending and p not in fetched:
                    new_pending.append(p)

        added_internal = len(new_pending) - len(rest)
        if added_internal:
            _log.info(
                "Nó [fetch_one]: %d novas páginas HTML enfileiradas (%s).",
                added_internal,
                "escopo PCDT" if strict else f"dica de caminho={hint!r}",
            )

        done = len(fetched) + 1 >= max_pages or not new_pending
        _log.info(
            "Nó [fetch_one]: total acumulado de URLs PDF únicas=%d; discovery_done=%s (fila restante=%d).",
            len(pdf_urls),
            done,
            len(new_pending),
        )
        return {
            "pending_pages": new_pending,
            "fetched_pages": fetched + [url],
            "pdf_urls": pdf_urls,
            "current_html": html[:500] if html else None,
            "current_fetch_url": url,
            "errors": errors,
            "discovery_done": done,
        }

    return fetch_one


def route_discovery(state: PCDTIngestState) -> Literal["fetch_one", "download_pdfs"]:
    if state.get("discovery_done"):
        _log.info("Roteador: indo para [download_pdfs] (descoberta concluída).")
        return "download_pdfs"
    _log.info("Roteador: voltando para [fetch_one] (ainda há páginas na fila).")
    return "fetch_one"


def build_download_pdfs(raw_dir: Path):
    def download_pdfs(state: PCDTIngestState) -> dict[str, Any]:
        max_files = int(state.get("max_files") or 500)
        pdf_urls = list(state.get("pdf_urls") or [])
        errors = list(state.get("errors") or [])
        ua = (state.get("user_agent") or "").strip() or DEFAULT_USER_AGENT
        timeout = float(state.get("request_timeout_s") or 120.0)

        raw_dir.mkdir(parents=True, exist_ok=True)
        entries: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()
        used_names: set[str] = set()

        total = min(len(pdf_urls), max_files)
        _log.info(
            "Nó [download_pdfs]: baixando até %d arquivo(s) (de %d URLs PDF descobertos)…",
            total,
            len(pdf_urls),
        )

        client = HttpxFetcher(user_agent=ua, timeout_s=timeout)
        try:
            for i, url in enumerate(pdf_urls[:max_files], start=1):
                try:
                    _log.info("Nó [download_pdfs]: [%d/%d] GET %s", i, total, url)
                    status, data, ctype = client.get_bytes(url)
                    if status >= 400:
                        _log.warning(
                            "Nó [download_pdfs]: [%d/%d] HTTP %s para %s",
                            i,
                            total,
                            status,
                            url,
                        )
                        entries.append(
                            {
                                "id": _doc_id_from_url(url),
                                "source_url": url,
                                "title": None,
                                "fetched_at": now_iso(),
                                "content_type": ctype,
                                "bytes": 0,
                                "sha256": "",
                                "relative_path": "",
                                "status": "error",
                                "detail": f"HTTP {status}",
                            }
                        )
                        continue
                    sha = hashlib.sha256(data).hexdigest()
                    if sha in seen_hashes:
                        _log.info(
                            "Nó [download_pdfs]: [%d/%d] ignorado (SHA-256 duplicado) %s",
                            i,
                            total,
                            url,
                        )
                        entries.append(
                            {
                                "id": _doc_id_from_url(url),
                                "source_url": url,
                                "title": Path(urlparse(url).path).stem,
                                "fetched_at": now_iso(),
                                "content_type": ctype,
                                "bytes": len(data),
                                "sha256": sha,
                                "relative_path": "",
                                "status": "skipped",
                                "detail": "duplicate_sha256",
                            }
                        )
                        continue
                    seen_hashes.add(sha)

                    name = local_filename(url, ctype)
                    if name in used_names:
                        stem = Path(name).stem
                        suffix = Path(name).suffix or ".pdf"
                        name = f"{stem}_{sha[:8]}{suffix}"
                    used_names.add(name)

                    rel = Path("raw/pcdt") / name
                    out_path = raw_dir / name
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(data)

                    entries.append(
                        {
                            "id": _doc_id_from_url(url),
                            "source_url": url,
                            "title": Path(name).stem,
                            "fetched_at": now_iso(),
                            "content_type": ctype,
                            "bytes": len(data),
                            "sha256": sha,
                            "relative_path": str(rel).replace("\\", "/"),
                            "status": "ok",
                        }
                    )
                    _log.info(
                        "Nó [download_pdfs]: [%d/%d] salvo %s (%d bytes)",
                        i,
                        total,
                        rel,
                        len(data),
                    )
                except Exception as e:  # noqa: BLE001
                    _log.warning("Nó [download_pdfs]: [%d/%d] falha: %s", i, total, e)
                    errors.append(f"Download falhou {url}: {e!s}")
                    entries.append(
                        {
                            "id": _doc_id_from_url(url),
                            "source_url": url,
                            "title": None,
                            "fetched_at": now_iso(),
                            "content_type": None,
                            "bytes": 0,
                            "sha256": "",
                            "relative_path": "",
                            "status": "error",
                            "detail": str(e),
                        }
                    )
        finally:
            client.close()

        _log.info(
            "Nó [download_pdfs]: fim (ok=%s, skipped=%s, erro=%s).",
            sum(1 for e in entries if e.get("status") == "ok"),
            sum(1 for e in entries if e.get("status") == "skipped"),
            sum(1 for e in entries if e.get("status") == "error"),
        )
        return {"download_entries": entries, "errors": errors}

    return download_pdfs


def build_write_manifest(manifests_dir: Path, run_version: str):
    def write_manifest(state: PCDTIngestState) -> dict[str, Any]:
        entries = list(state.get("download_entries") or [])
        pcdt_path = manifests_dir / "pcdt_index.jsonl"
        _log.info(
            "Nó [write_manifest]: gravando %d linhas em %s",
            len(entries),
            pcdt_path,
        )
        write_jsonl(pcdt_path, entries)

        summary = {
            "run_at": now_iso(),
            "script_version": run_version,
            "base_urls_crawled": list(dict.fromkeys(state.get("fetched_pages") or [])),
            "pdf_urls_discovered": len(state.get("pdf_urls") or []),
            "counts": {
                "ok": sum(1 for e in entries if e.get("status") == "ok"),
                "skipped": sum(1 for e in entries if e.get("status") == "skipped"),
                "error": sum(1 for e in entries if e.get("status") == "error"),
            },
            "errors": state.get("errors") or [],
        }
        run_path = manifests_dir / "download_run.json"
        write_json(run_path, summary)
        _log.info("Nó [write_manifest]: resumo em %s", run_path)
        return {}

    return write_manifest


def compile_pcdt_workflow(*, use_playwright: bool = False):
    """Compila grafo com mapeamento explícito de arestas condicionais."""
    ensure_data_dirs()
    base = ensure_data_dirs()
    raw_pcdt = base / "raw" / "pcdt"
    manifests = base / "manifests"

    g = StateGraph(PCDTIngestState)
    g.add_node("init", node_init)
    g.add_node("fetch_one", build_fetch_one(use_playwright))
    g.add_node("download_pdfs", build_download_pdfs(raw_pcdt))
    g.add_node("write_manifest", build_write_manifest(manifests, run_version="0.1.0"))

    g.set_entry_point("init")
    g.add_edge("init", "fetch_one")
    g.add_conditional_edges(
        "fetch_one",
        route_discovery,
        {
            "fetch_one": "fetch_one",
            "download_pdfs": "download_pdfs",
        },
    )
    g.add_edge("download_pdfs", "write_manifest")
    g.add_edge("write_manifest", END)

    return g.compile()
