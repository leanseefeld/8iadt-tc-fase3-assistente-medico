"""CLI: ingestão PCDT a partir da tabela da página de listagem CONITEC."""

from __future__ import annotations

import argparse
import sys

from pcdt_ingest.logutil import configure_logging, get_logger
from pcdt_ingest.pcdt_download import run_pcdt_download
from pcdt_ingest.paths import (
    DIR_MANIFESTS,
    DIR_RAW_PCDT,
    MANIFEST_PCDT_INDEX,
    data_root,
    ensure_data_dirs,
    has_prior_pcdt_run,
)

DEFAULT_LISTING = (
    "https://www.gov.br/conitec/pt-br/assuntos/"
    "avaliacao-de-tecnologias-em-saude/protocolos-clinicos-e-diretrizes-terapeuticas"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Baixa documentos cujos links constam na tabela PCDT da página de listagem "
            "CONITEC (uma única URL, sem crawl)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_LISTING,
        help="URL da página de listagem PCDT na CONITEC.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=500,
        help="Máximo de arquivos a baixar nesta execução (ordem da tabela).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="Timeout HTTP por requisição (segundos).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Menos saída no console (só avisos e erros).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Executa mesmo se já existir ingestão PCDT anterior (manifesto ou arquivos "
            "em raw/pcdt), sobrescrevendo o índice e baixando de novo."
        ),
    )
    args = parser.parse_args(argv)

    configure_logging(quiet=args.quiet)
    log = get_logger("cli")

    ensure_data_dirs()
    root = data_root()
    manifests_dir = root / DIR_MANIFESTS

    if not args.force and has_prior_pcdt_run(root):
        print(
            "Erro: já existe uma execução anterior de ingestão PCDT (arquivo "
            f"{(root / DIR_MANIFESTS / MANIFEST_PCDT_INDEX).as_posix()} com conteúdo "
            f"ou arquivos em {(root / DIR_RAW_PCDT).as_posix()}). "
            "Para sobrescrever, use a opção --force.",
            file=sys.stderr,
        )
        return 1

    log.info(
        "Iniciando ingestão PCDT (max_files=%s, timeout=%ss).",
        args.max_files,
        args.timeout,
    )
    log.info("URL da listagem: %s", args.url)
    log.info("Diretório de dados: %s", root)

    final = run_pcdt_download(
        listing_url=args.url,
        max_files=args.max_files,
        timeout_s=args.timeout,
        user_agent="",
    )

    n_ok = sum(1 for e in final.get("download_entries") or [] if e.get("status") == "ok")
    log.info("Concluído. Arquivos salvos (status=ok): %s. Manifestos em %s", n_ok, manifests_dir)
    print(f"Concluído. Arquivos salvos (status=ok): {n_ok}. Manifestos em {manifests_dir}")
    errs = final.get("errors") or []
    if errs:
        print(f"Avisos/erros ({len(errs)}):", file=sys.stderr)
        for line in errs[:20]:
            print(f"  {line}", file=sys.stderr)
        if len(errs) > 20:
            print("  ...", file=sys.stderr)
    return 0 if n_ok or not errs else 1


if __name__ == "__main__":
    raise SystemExit(main())
