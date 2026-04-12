"""Download do conjunto Einstein (USP Data Sharing / handle item 98)."""

from __future__ import annotations

import hashlib
import re
import tempfile
import zipfile
from pathlib import Path

from pcdt_ingest.manifest import now_iso, write_json, write_jsonl
from pcdt_ingest.paths import (
    DIR_MANIFESTS,
    DIR_RAW_CLINICAL_EXAMS,
    MANIFEST_CLINICAL_EXAMS_INDEX,
    MANIFEST_CLINICAL_EXAMS_RUN,
    data_root,
    ensure_data_dirs,
)

DEFAULT_HANDLE_URL = (
    "https://repositoriodatasharingfapesp.uspdigital.usp.br/handle/item/98"
)


def extract_and_catalog(
    zip_path: Path,
    target_dir: Path,
    source_url: str,
) -> list[dict]:
    """Extrai o ZIP em *target_dir* e retorna linhas de manifesto (uma por arquivo + uma para o ZIP)."""
    ts = now_iso()
    rows: list[dict] = []

    zip_data = zip_path.read_bytes()
    zip_sha = hashlib.sha256(zip_data).hexdigest()
    zip_rel = DIR_RAW_CLINICAL_EXAMS / zip_path.name
    rows.append(
        {
            "id": hashlib.sha256(str(zip_rel).encode()).hexdigest()[:16],
            "source_url": source_url,
            "archive": zip_path.name,
            "title": zip_path.name,
            "fetched_at": ts,
            "bytes": len(zip_data),
            "sha256": zip_sha,
            "relative_path": zip_rel.as_posix(),
            "status": "ok",
        }
    )

    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            zf.extract(info, target_dir)
            extracted = target_dir / info.filename
            file_data = extracted.read_bytes()
            sha = hashlib.sha256(file_data).hexdigest()
            rel = DIR_RAW_CLINICAL_EXAMS / info.filename
            rows.append(
                {
                    "id": hashlib.sha256(str(rel).encode()).hexdigest()[:16],
                    "source_url": source_url,
                    "archive": zip_path.name,
                    "title": info.filename,
                    "fetched_at": ts,
                    "bytes": info.file_size,
                    "sha256": sha,
                    "relative_path": rel.as_posix(),
                    "status": "ok",
                }
            )

    return rows


def _write_manifests(rows: list[dict], handle_url: str) -> None:
    manifests_dir = data_root() / DIR_MANIFESTS
    write_jsonl(manifests_dir / MANIFEST_CLINICAL_EXAMS_INDEX, rows)
    write_json(
        manifests_dir / MANIFEST_CLINICAL_EXAMS_RUN,
        {
            "run_at": now_iso(),
            "handle_url": handle_url,
            "counts": {
                "ok": sum(1 for r in rows if r.get("status") == "ok"),
                "error": sum(1 for r in rows if r.get("status") == "error"),
            },
        },
    )


def download_einstein_via_browser(
    *,
    handle_url: str = DEFAULT_HANDLE_URL,
    download_timeout_ms: int = 300_000,
) -> list[dict]:
    """
    Abre o navegador para o usuário aceitar os termos do repositório,
    captura o download e extrai o ZIP em ``llm/data/raw/clinical_exams/``.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright não está instalado. Execute:\n"
            "  pip install -e . && playwright install chromium"
        ) from None

    base = ensure_data_dirs()
    raw_dir = base / DIR_RAW_CLINICAL_EXAMS

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(accept_downloads=True, locale="pt-BR")
        page = context.new_page()

        page.goto(handle_url, wait_until="domcontentloaded")

        view_link = page.locator(
            "a", has_text=re.compile(r"Visualizar|View.Open", re.IGNORECASE)
        ).first
        view_link.click()

        print(
            "\n╔══════════════════════════════════════════════════════════════╗\n"
            "║  Preencha nome, e-mail e aceite os termos no navegador.      ║\n"
            "║  O download será capturado automaticamente.                  ║\n"
            "╚══════════════════════════════════════════════════════════════╝\n"
        )

        with page.expect_download(timeout=download_timeout_ms) as dl_info:
            pass
        download = dl_info.value

        tmp_dir = Path(tempfile.mkdtemp())
        tmp_zip = tmp_dir / (download.suggested_filename or "einstein.zip")
        download.save_as(tmp_zip)

        print(f"Download concluído: {tmp_zip.name} ({tmp_zip.stat().st_size:,} bytes)")

        browser.close()

    rows = extract_and_catalog(tmp_zip, raw_dir, handle_url)
    _write_manifests(rows, handle_url)
    return rows


def ingest_local_zip(
    zip_path: Path,
    *,
    handle_url: str = DEFAULT_HANDLE_URL,
) -> list[dict]:
    """Extrai um ZIP já baixado manualmente e grava manifestos — sem Playwright."""
    if not zip_path.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {zip_path}")

    base = ensure_data_dirs()
    raw_dir = base / DIR_RAW_CLINICAL_EXAMS

    rows = extract_and_catalog(zip_path, raw_dir, handle_url)
    _write_manifests(rows, handle_url)
    return rows
