"""CLI para gerar o catálogo local Conitec PCDT/CID/medicamentos."""

from __future__ import annotations

import argparse
from pathlib import Path

from pcdt_ingest.logutil import configure_logging
from pcdt_ingest.paths import data_root, ensure_data_dirs
from pcdt_ingest.reference_data.conitec_catalog import (
    CONITEC_CATALOG_URL,
    DEFAULT_CATALOG_RELATIVE_PATH,
    build_and_write_catalog,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gera llm/data/processed/conitec/pcdt_catalog.jsonl a partir da planilha oficial Conitec.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input",
        default=CONITEC_CATALOG_URL,
        help="Caminho local .xlsx ou URL da planilha. Se omitido, usa a URL oficial Conitec.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Arquivo JSONL de saída. Default: llm/data/processed/conitec/pcdt_catalog.jsonl.",
    )
    parser.add_argument("--quiet", action="store_true", help="Menos saída no console.")
    args = parser.parse_args(argv)

    configure_logging(quiet=args.quiet)
    ensure_data_dirs()
    output = args.output or (data_root() / DEFAULT_CATALOG_RELATIVE_PATH)
    catalog = build_and_write_catalog(args.input, output)
    print(f"Catálogo Conitec gerado: {output} ({len(catalog)} diretrizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
