"""CLI: fragmenta ``*.pages.jsonl`` em ``*.chunks.jsonl`` com metadata."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pcdt_ingest.clean.cleaner import CLEANED_PAGE_JSONL_SUFFIX, default_cleaned_processed_dir
from pcdt_ingest.chunk import chunk_one_stem, default_chunks_dir, sidecar_stem
from pcdt_ingest.extract import PAGE_JSONL_SUFFIX, default_processed_dir
from pcdt_ingest.logutil import configure_logging, get_logger
from pcdt_ingest.manifest import write_jsonl
from pcdt_ingest.paths import (
    DIR_MANIFESTS,
    MANIFEST_PCDT_CHUNK,
    MANIFEST_PCDT_INDEX,
    data_root,
    ensure_data_dirs,
)
from pcdt_ingest.pipeline_config import get_config
from pcdt_ingest.reference_data.conitec_catalog import (
    DEFAULT_CATALOG_RELATIVE_PATH,
    read_catalog_jsonl,
)

_log = get_logger("cli_chunk")


def _load_manifest_stems(root: Path) -> list[str]:
    """Stems dos PDFs com status ok no índice PCDT (ficheiro em ``raw/pcdt``)."""
    index_path = root / DIR_MANIFESTS / MANIFEST_PCDT_INDEX
    if not index_path.is_file():
        raise FileNotFoundError(
            f"Manifesto não encontrado: {index_path}. Execute download-pcdt antes ou "
            "não use --only-manifest."
        )
    stems: set[str] = set()
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
                stems.add(p.stem)
    return sorted(stems)


def _list_sidecar_stems(processed_dir: Path, cleaned_dir: Path) -> list[str]:
    """Stems com sidecar extraído; prefere ``*.pages.cleaned.jsonl`` no processamento."""
    out: set[str] = set()
    for f in sorted(cleaned_dir.glob(f"*{CLEANED_PAGE_JSONL_SUFFIX}")):
        out.add(sidecar_stem(f))
    for f in sorted(processed_dir.glob(f"*{PAGE_JSONL_SUFFIX}")):
        out.add(sidecar_stem(f))
    return sorted(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Lê llm/data/processed/pcdt_cleaned/<nome>.pages.cleaned.jsonl quando existir "
            "ou llm/data/processed/pcdt/<nome>.pages.jsonl como fallback, e grava "
            "llm/data/chunks/pcdt/<nome>.chunks.jsonl (metadata: seção, páginas, etc.)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refaz chunks mesmo se o ficheiro .chunks.jsonl estiver em dia.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Processa no máximo N documentos (ordem por stem).",
    )
    parser.add_argument(
        "--only-manifest",
        action="store_true",
        help="Só stems presentes em manifests/pcdt_index.jsonl com status=ok.",
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
        help="Threads para processar vários stems em paralelo.",
    )
    parser.add_argument(
        "--chunk-strategy",
        choices=["recursive", "semantic"],
        default=str(get_config("CHUNK_STRATEGY", "recursive")),
        help="Estratégia de chunking: recursive mantém o modo antigo; semantic usa SemanticChunker por seção.",
    )
    parser.add_argument(
        "--semantic-breakpoint-percentile",
        type=int,
        default=int(get_config("SEMANTIC_BREAKPOINT_PERCENTILE", 85)),
        help="Percentil de breakpoint usado pelo SemanticChunker quando --chunk-strategy semantic.",
    )
    parser.add_argument(
        "--chunk-tokens",
        type=int,
        default=int(get_config("CHUNK_TOKENS", 400)),
        help="Tamanho alvo de chunk em tokens estimados.",
    )
    parser.add_argument(
        "--overlap-tokens",
        type=int,
        default=int(get_config("CHUNK_OVERLAP_TOKENS", 50)),
        help="Sobreposição entre chunks em tokens estimados.",
    )
    parser.add_argument(
        "--conitec-catalog",
        type=Path,
        default=None,
        help=(
            "Catálogo Conitec JSONL para enriquecer disease/CID/medicamentos. "
            "Se omitido, usa llm/data/processed/conitec/pcdt_catalog.jsonl quando existir."
        ),
    )
    parser.add_argument(
        "--no-conitec-catalog",
        action="store_true",
        help="Desativa enriquecimento pelo catálogo Conitec e usa apenas a heurística antiga.",
    )
    args = parser.parse_args(argv)

    if args.workers < 1:
        print("Erro: --workers deve ser >= 1.", file=sys.stderr)
        return 2
    configure_logging(quiet=args.quiet)
    if args.chunk_strategy == "semantic":
        semantic_max_workers = int(get_config("SEMANTIC_MAX_WORKERS", 1))
        if args.workers > semantic_max_workers:
            _log.warning(
                "Chunking semântico usa embeddings via Ollama; reduzindo workers de %s para %s.",
                args.workers,
                semantic_max_workers,
            )
            args.workers = semantic_max_workers
        elif args.workers > 1:
            _log.info(
                "Chunking semântico com workers=%s; o Ollama receberá chamadas concorrentes de embedding.",
                args.workers,
            )

    ensure_data_dirs()
    root = data_root()
    processed_dir = default_processed_dir()
    cleaned_dir = default_cleaned_processed_dir()
    chunks_dir = default_chunks_dir()
    manifests_dir = root / DIR_MANIFESTS
    conitec_catalog: dict[str, dict] | None = None
    conitec_catalog_mtime: float | None = None
    if not args.no_conitec_catalog:
        catalog_path = args.conitec_catalog or (root / DEFAULT_CATALOG_RELATIVE_PATH)
        if catalog_path.is_file():
            conitec_catalog = read_catalog_jsonl(catalog_path)
            conitec_catalog_mtime = catalog_path.stat().st_mtime
            _log.info("catálogo Conitec carregado: %s (%s diretrizes)", catalog_path, len(conitec_catalog))
        elif args.conitec_catalog:
            print(f"Erro: catálogo Conitec não encontrado: {catalog_path}", file=sys.stderr)
            return 2

    if args.only_manifest:
        stems = _load_manifest_stems(root)
    else:
        stems = _list_sidecar_stems(processed_dir, cleaned_dir)

    if args.max_files is not None:
        stems = stems[: max(0, args.max_files)]

    if not stems:
        print("Nenhum ficheiro .pages.jsonl encontrado.", file=sys.stderr)
        return 1
    _log.info(
        "chunk-pcdt: %s documentos strategy=%s workers=%s chunk_tokens=%s overlap_tokens=%s",
        len(stems),
        args.chunk_strategy,
        args.workers,
        args.chunk_tokens,
        args.overlap_tokens,
    )

    def _run_one(stem: str) -> dict:
        _log.info("%s: iniciando fragmentação", stem)
        row = chunk_one_stem(
            stem,
            processed_dir=processed_dir,
            cleaned_dir=cleaned_dir,
            chunks_dir=chunks_dir,
            data_base=root,
            force=args.force,
            chunk_strategy=args.chunk_strategy,
            semantic_breakpoint_percentile=args.semantic_breakpoint_percentile,
            chunk_tokens=args.chunk_tokens,
            overlap_tokens=args.overlap_tokens,
            conitec_catalog=conitec_catalog,
            conitec_catalog_mtime=conitec_catalog_mtime,
        )
        _log.info("%s: %s (%s chunks)", stem, row.get("status"), row.get("chunk_count"))
        return row

    if args.workers <= 1:
        rows = [_run_one(s) for s in stems]
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(_run_one, stems))

    out_manifest = manifests_dir / MANIFEST_PCDT_CHUNK
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
