"""CLI: download do dataset Einstein (handle USP)."""

from __future__ import annotations

import argparse
import sys

from pcdt_ingest.exams_fetch import DEFAULT_HANDLE_URL, download_clinical_exams_bundle
from pcdt_ingest.paths import data_root, ensure_data_dirs


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
        "--timeout",
        type=float,
        default=120.0,
        help="Timeout HTTP (segundos).",
    )
    args = parser.parse_args(argv)

    ensure_data_dirs()
    rows = download_clinical_exams_bundle(handle_url=args.url, timeout_s=args.timeout)
    n_ok = sum(1 for r in rows if r.get("status") == "ok")
    n_err = sum(1 for r in rows if r.get("status") == "error")
    print(f"Concluído. Artefatos OK: {n_ok}, com erro: {n_err}. Dados em {data_root()}/raw/clinical_exams/")
    if not rows:
        print(
            "Nenhum link de arquivo encontrado; a página pode ter mudado.",
            file=sys.stderr,
        )
        return 1
    if n_ok == 0 and n_err:
        print(
            "Nenhum download binário concluído. Verifique termos de uso no repositório ou use sessão/cookies.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
