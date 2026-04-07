"""CLI: download do dataset Einstein (handle USP)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pcdt_ingest.exams_fetch import (
    DEFAULT_HANDLE_URL,
    download_einstein_via_browser,
    ingest_local_zip,
)
from pcdt_ingest.paths import data_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Baixa arquivos do repositório Einstein (USP Data Sharing, item 98).",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_HANDLE_URL,
        help="URL da página do item no repositório.",
    )
    parser.add_argument(
        "--zip",
        type=str,
        default=None,
        metavar="ZIP_PATH",
        help=(
            "Caminho para um ZIP já baixado manualmente. "
            "Pula o fluxo de navegador e vai direto para extração."
        ),
    )
    parser.add_argument(
        "--download-timeout",
        type=int,
        default=300,
        help="Tempo máximo (segundos) para aguardar o download no navegador (padrão: 300).",
    )
    args = parser.parse_args(argv)

    if args.zip:
        rows = ingest_local_zip(Path(args.zip), handle_url=args.url)
    else:
        try:
            rows = download_einstein_via_browser(
                handle_url=args.url,
                download_timeout_ms=args.download_timeout * 1000,
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except TimeoutError:
            print(
                "Tempo esgotado aguardando o download. "
                "Tente novamente ou baixe manualmente e use --zip.",
                file=sys.stderr,
            )
            return 1

    n_ok = sum(1 for r in rows if r.get("status") == "ok")
    n_err = sum(1 for r in rows if r.get("status") == "error")
    print(f"Concluído. Artefatos OK: {n_ok}, com erro: {n_err}. Dados em {data_root()}/raw/clinical_exams/")

    if not rows:
        print(
            "Nenhum arquivo extraído; verifique o conteúdo do ZIP.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
