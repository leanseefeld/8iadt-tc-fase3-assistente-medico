"""CLI: limpa ``*.pages.jsonl`` e grava ``*.pages.cleaned.jsonl``."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pcdt_ingest.clean.cleaner import (
    clean_one_stem,
    clean_pages_jsonl,
    default_cleaned_processed_dir,
    default_output_path,
)
from pcdt_ingest.clean.heuristics import default_config
from pcdt_ingest.clean.models import CleanStats
from pcdt_ingest.extract import PAGE_JSONL_SUFFIX, default_processed_dir
from pcdt_ingest.logutil import configure_logging, get_logger
from pcdt_ingest.manifest import write_jsonl
from pcdt_ingest.paths import (
    DIR_MANIFESTS,
    MANIFEST_PCDT_CLEAN,
    data_root,
    ensure_data_dirs,
)

_log = get_logger("cli_clean")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lê llm/data/processed/pcdt/<nome>.pages.jsonl, aplica limpeza estrutural "
            "e grava llm/data/processed/pcdt_cleaned/<nome>.pages.cleaned.jsonl. "
            "O cli_chunk passa a preferir o sidecar limpo."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help=(
            "Arquivo .pages.jsonl avulso. Sem esta opção, processa "
            "llm/data/processed/pcdt/*.pages.jsonl por stem."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Arquivo de saída para uso com --input avulso.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refaz limpeza mesmo se o .pages.cleaned.jsonl em pcdt_cleaned estiver em dia.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Não grava arquivos; só mostra resumo da limpeza.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Processa no máximo N documentos (ordem por stem).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Menos saída no console (só avisos e erros).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Registra resumo detalhado por arquivo limpo.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help="Threads para processar vários stems em paralelo.",
    )
    parser.add_argument(
        "--header-footer-threshold",
        type=float,
        default=0.5,
        help="Frequência mínima para remover header/footer repetido.",
    )
    parser.add_argument(
        "--min-words",
        type=int,
        default=6,
        help="Mínimo de palavras para não classificar texto curto como junk.",
    )
    return parser.parse_args(argv)


def _list_sidecar_stems(processed_dir: Path) -> list[str]:
    """Stems que têm ``{stem}.pages.jsonl`` em ``processed_dir``."""
    out: list[str] = []
    for f in sorted(processed_dir.glob(f"*{PAGE_JSONL_SUFFIX}")):
        if f.name.endswith(".pages.cleaned.jsonl"):
            continue
        out.append(f.name[: -len(PAGE_JSONL_SUFFIX)])
    return out


def _stats_from_rows(rows: list[dict]) -> CleanStats:
    total = CleanStats()
    for row in rows:
        stats = row.get("stats")
        if not isinstance(stats, dict):
            continue
        total.merge(CleanStats(**{k: int(v) for k, v in stats.items() if k in CleanStats.__dataclass_fields__}))
    return total


def _run_single_input(args: argparse.Namespace) -> int:
    input_path = args.input
    if not isinstance(input_path, Path) or not input_path.is_file():
        print(f"Erro: --input não encontrado: {input_path}", file=sys.stderr)
        return 1
    output_path = args.output or default_output_path(input_path)
    cfg = default_config(
        header_footer_threshold=float(args.header_footer_threshold),
        min_words=int(args.min_words),
    )
    try:
        stats, written, doc_class = clean_pages_jsonl(
            input_path,
            output_path=output_path,
            config=cfg,
            dry_run=bool(args.dry_run),
            force=bool(args.force),
        )
    except FileExistsError as exc:
        print(f"Erro: {exc}. Use --force para sobrescrever.", file=sys.stderr)
        return 1
    except Exception as exc:
        _log.exception("Falha ao limpar %s", input_path)
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    action = "dry-run" if args.dry_run else f"gravado={written}"
    _log.info(
        "%s: %s class=%s pages=%s skipped=%s removed_lines=%s",
        input_path.name,
        action,
        doc_class,
        stats.pages_analyzed,
        stats.pages_skipped,
        stats.lines_removed,
    )
    print(f"Concluído. ok=1 skipped=0 error=0. Saída: {written}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.workers < 1:
        print("Erro: --workers deve ser >= 1.", file=sys.stderr)
        return 2
    if args.input is not None and args.max_files is not None:
        print("Erro: --max-files só se aplica ao modo por diretório/stem.", file=sys.stderr)
        return 2
    if args.output is not None and args.input is None:
        print("Erro: --output só pode ser usado junto com --input.", file=sys.stderr)
        return 2

    configure_logging(quiet=args.quiet, verbose=args.verbose)
    ensure_data_dirs()

    if args.input is not None:
        return _run_single_input(args)

    root = data_root()
    processed_dir = default_processed_dir()
    cleaned_dir = default_cleaned_processed_dir()
    manifests_dir = root / DIR_MANIFESTS
    cfg = default_config(
        header_footer_threshold=float(args.header_footer_threshold),
        min_words=int(args.min_words),
    )

    stems = _list_sidecar_stems(processed_dir)
    if args.max_files is not None:
        stems = stems[: max(0, args.max_files)]

    if not stems:
        print("Nenhum ficheiro .pages.jsonl encontrado.", file=sys.stderr)
        return 1

    def _run_one(stem: str) -> dict:
        row = clean_one_stem(
            stem,
            processed_dir=processed_dir,
            cleaned_dir=cleaned_dir,
            data_base=root,
            force=bool(args.force),
            dry_run=bool(args.dry_run),
            config=cfg,
        )
        stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
        _log.info(
            "%s: %s class=%s pages=%s skipped=%s removed_lines=%s",
            stem,
            row.get("status"),
            row.get("document_class"),
            stats.get("pages_analyzed", 0),
            stats.get("pages_skipped", 0),
            stats.get("lines_removed", 0),
        )
        return row

    if args.workers <= 1:
        rows = [_run_one(s) for s in stems]
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(_run_one, stems))

    out_manifest = manifests_dir / MANIFEST_PCDT_CLEAN
    if not args.dry_run:
        write_jsonl(out_manifest, rows)

    n_ok = sum(1 for r in rows if r.get("status") == "ok")
    n_dry = sum(1 for r in rows if r.get("status") == "dry_run")
    n_skip = sum(1 for r in rows if r.get("status") == "skipped")
    n_err = sum(1 for r in rows if r.get("status") == "error")
    total = _stats_from_rows(rows)
    print(
        f"Concluído. ok={n_ok} dry_run={n_dry} skipped={n_skip} error={n_err}. "
        f"pages={total.pages_analyzed} skipped_pages={total.pages_skipped} "
        f"removed_lines={total.lines_removed}. "
        f"Manifesto: {'não gravado (--dry-run)' if args.dry_run else out_manifest}"
    )
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())