"""CLI: fragmenta ``*.pages.jsonl`` em ``*.chunks.jsonl`` com metadata."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pcdt_ingest.chunk import chunk_one_stem, default_chunks_dir
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


def _list_sidecar_stems(processed_dir: Path) -> list[str]:
    """Stems que têm ``{stem}.pages.jsonl`` em ``processed_dir``."""
    out: list[str] = []
    for f in sorted(processed_dir.glob(f"*{PAGE_JSONL_SUFFIX}")):
        stem = f.name[: -len(PAGE_JSONL_SUFFIX)]
        out.append(stem)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Lê llm/data/processed/pcdt/<nome>.pages.jsonl e grava "
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
    args = parser.parse_args(argv)

    if args.workers < 1:
        print("Erro: --workers deve ser >= 1.", file=sys.stderr)
        return 2

    configure_logging(quiet=args.quiet)
    ensure_data_dirs()
    root = data_root()
    processed_dir = default_processed_dir()
    chunks_dir = default_chunks_dir()
    manifests_dir = root / DIR_MANIFESTS

    if args.only_manifest:
        stems = _load_manifest_stems(root)
    else:
        stems = _list_sidecar_stems(processed_dir)

    if args.max_files is not None:
        stems = stems[: max(0, args.max_files)]

    if not stems:
        print("Nenhum ficheiro .pages.jsonl encontrado.", file=sys.stderr)
        return 1

    def _run_one(stem: str) -> dict:
        row = chunk_one_stem(
            stem,
            processed_dir=processed_dir,
            chunks_dir=chunks_dir,
            data_base=root,
            force=args.force,
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
