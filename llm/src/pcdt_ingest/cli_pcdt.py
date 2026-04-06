"""CLI: executa o grafo de ingestão PCDT."""

from __future__ import annotations

import argparse
import sys

from pcdt_ingest.graph import compile_pcdt_workflow
from pcdt_ingest.logutil import configure_logging, get_logger
from pcdt_ingest.paths import data_root, ensure_data_dirs

DEFAULT_LISTING = (
    "https://www.gov.br/conitec/pt-br/assuntos/"
    "avaliacao-de-tecnologias-em-saude/protocolos-clinicos-e-diretrizes-terapeuticas"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Baixa PDFs PCDT listados no site CONITEC (LangGraph).",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_LISTING,
        help="URL semente da listagem CONITEC.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=40,
        help="Máximo de páginas HTML a buscar na fase de descoberta.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=500,
        help="Máximo de PDFs a baixar nesta execução.",
    )
    parser.add_argument(
        "--no-follow",
        action="store_true",
        help="Não seguir links HTML internos (apenas extrai PDFs da semente).",
    )
    parser.add_argument(
        "--all-conitec-pdfs",
        action="store_true",
        help=(
            "Desliga o filtro PCDT: rastrear qualquer PDF gov.br encontrado no crawl "
            "(comportamento antigo; inclui cartilhas, OSC, notícias, etc.)."
        ),
    )
    parser.add_argument(
        "--playwright",
        action="store_true",
        help="Usar Playwright para obter HTML (requer: pip install assistente-medico-llm[playwright] e playwright install chromium).",
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
    args = parser.parse_args(argv)

    configure_logging(quiet=args.quiet)
    log = get_logger("cli")

    ensure_data_dirs()
    out = str(data_root())

    initial = {
        "listing_seed_url": args.url,
        "output_root": out,
        "max_pages": args.max_pages,
        "max_files": args.max_files,
        "follow_internal_html": not args.no_follow,
        "conitec_path_hint": "conitec",
        "strict_pcdt_only": not args.all_conitec_pdfs,
        "user_agent": "",
        "request_timeout_s": args.timeout,
    }

    log.info(
        "Iniciando ingestão PCDT (playwright=%s, max_pages=%s, max_files=%s, timeout=%ss, escopo=%s).",
        args.playwright,
        args.max_pages,
        args.max_files,
        args.timeout,
        "PCDT" if initial["strict_pcdt_only"] else "CONITEC ampliado",
    )
    log.info("URL semente: %s", args.url)
    log.info("Diretório de dados: %s", out)

    app = compile_pcdt_workflow(use_playwright=args.playwright)
    final = app.invoke(initial)

    n_ok = sum(1 for e in final.get("download_entries") or [] if e.get("status") == "ok")
    log.info("Concluído. PDFs salvos (status=ok): %s. Manifestos em %s/manifests/", n_ok, out)
    print(f"Concluído. PDFs salvos (status=ok): {n_ok}. Manifestos em {out}/manifests/")
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
