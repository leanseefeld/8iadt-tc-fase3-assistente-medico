"""CLI: extrai PDFs PCDT para sidecar JSONL por página; MD combinado opcional."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pcdt_ingest.extract import default_processed_dir, extract_one_pdf
from pcdt_ingest.logutil import configure_logging, get_logger
from pcdt_ingest.manifest import write_jsonl
from pcdt_ingest.paths import (
    DIR_MANIFESTS,
    DIR_RAW_PCDT,
    MANIFEST_PCDT_INDEX,
    MANIFEST_PCDT_MD_EXTRACT,
    data_root,
    ensure_data_dirs,
)

_log = get_logger("cli_extract")


def _load_manifest_pdfs(root: Path) -> list[Path]:
    """Caminhos absolutos para PDFs com status ok no índice PCDT."""
    index_path = root / DIR_MANIFESTS / MANIFEST_PCDT_INDEX
    if not index_path.is_file():
        raise FileNotFoundError(
            f"Manifesto não encontrado: {index_path}. Execute download-pcdt antes ou "
            "não use --only-manifest."
        )
    out: list[Path] = []
    with index_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("status") != "ok":
                continue
            if row.get("content_type") != "application/pdf":
                continue
            rel = row.get("relative_path")
            if not rel:
                continue
            p = (root / rel).resolve()
            if p.suffix.lower() == ".pdf" and p.is_file():
                out.append(p)
    # Ordem estável por caminho
    return sorted(set(out), key=lambda x: x.as_posix())


def _list_all_pdfs(raw_dir: Path) -> list[Path]:
    return sorted(raw_dir.glob("*.pdf"), key=lambda p: p.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Converte PDFs em llm/data/raw/pcdt/ para sidecar JSONL "
            "(processed/pcdt/<nome>.pages.jsonl). "
            "O ficheiro Markdown combinado só é gerado com --with-combined-md."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--with-combined-md",
        action="store_true",
        help=(
            "Gera também processed/pcdt/<nome>.md (todas as páginas concatenadas). "
            "Sem esta flag, só são escritos os ficheiros .pages.jsonl."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Força reextração a partir do PDF (ignora sidecar em dia).",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Processa no máximo N PDFs (ordem por nome).",
    )
    parser.add_argument(
        "--only-manifest",
        action="store_true",
        help="Só PDFs listados em manifests/pcdt_index.jsonl com status=ok.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Menos saída no console (só avisos e erros).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Número de threads para processar PDFs em paralelo (cada thread trata "
            "um ficheiro de cada vez). Use 1 para sequencial."
        ),
    )
    args = parser.parse_args(argv)

    if args.workers < 1:
        print("Erro: --workers deve ser >= 1.", file=sys.stderr)
        return 2

    configure_logging(quiet=args.quiet)
    ensure_data_dirs()
    root = data_root()
    raw_dir = root / DIR_RAW_PCDT
    processed_dir = default_processed_dir()
    manifests_dir = root / DIR_MANIFESTS

    if args.only_manifest:
        pdfs = _load_manifest_pdfs(root)
    else:
        pdfs = _list_all_pdfs(raw_dir)

    if args.max_files is not None:
        pdfs = pdfs[: max(0, args.max_files)]

    if not pdfs:
        print(
            "Nenhum PDF encontrado.",
            file=sys.stderr,
        )
        return 1

    def _run_one(pdf_path: Path) -> dict:
        """Uma thread por invocação: extrai um PDF e registra o resultado."""
        row = extract_one_pdf(
            pdf_path,
            processed_dir=processed_dir,
            data_base=root,
            with_combined_md=args.with_combined_md,
            force=args.force,
        )
        _log.info("%s: %s", pdf_path.name, row.get("status"))
        return row

    # --- Paralelismo opcional: cada worker processa um PDF de cada vez ---
    if args.workers <= 1:
        rows = [_run_one(p) for p in pdfs]
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(_run_one, pdfs))

    out_manifest = manifests_dir / MANIFEST_PCDT_MD_EXTRACT
    write_jsonl(out_manifest, rows)

    n_ok = sum(1 for r in rows if r.get("status") == "ok")
    n_skip = sum(1 for r in rows if r.get("status") == "skipped")
    n_err = sum(1 for r in rows if r.get("status") == "error")
    print(
        f"Concluído. ok={n_ok} skipped={n_skip} error={n_err}. "
        f"Manifesto: {out_manifest}"
    )
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
