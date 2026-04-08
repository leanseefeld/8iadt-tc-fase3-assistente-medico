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
from pcdt_ingest.paths import (
    DIR_MANIFESTS,
    DIR_RAW_CLINICAL_EXAMS,
    MANIFEST_CLINICAL_EXAMS_INDEX,
    data_root,
    ensure_data_dirs,
    has_prior_clinical_exams_run,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Baixa arquivos do repositório Einstein (USP Data Sharing, item 98).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
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
        help="Tempo máximo (segundos) para aguardar o download no navegador.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Executa mesmo se já existir ingestão Einstein anterior (manifesto ou arquivos "
            "em raw/clinical_exams), sobrescrevendo manifestos e extraindo de novo."
        ),
    )
    args = parser.parse_args(argv)

    ensure_data_dirs()
    root = data_root()
    if not args.force and has_prior_clinical_exams_run(root):
        print(
            "Erro: já existe uma execução anterior de ingestão Einstein (arquivo "
            f"{(root / DIR_MANIFESTS / MANIFEST_CLINICAL_EXAMS_INDEX).as_posix()} com conteúdo "
            f"ou arquivos em {(root / DIR_RAW_CLINICAL_EXAMS).as_posix()}). "
            "Para sobrescrever, use a opção --force.",
            file=sys.stderr,
        )
        return 1

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
    raw_dir = data_root() / DIR_RAW_CLINICAL_EXAMS
    print(f"Concluído. Artefatos OK: {n_ok}, com erro: {n_err}. Dados em {raw_dir}")

    if not rows:
        print(
            "Nenhum arquivo extraído; verifique o conteúdo do ZIP.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
