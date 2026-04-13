"""CLI: indexa chunks PCDT no Chroma com embeddings Ollama (nomic-embed-text)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pcdt_ingest.embed import (
    CHROMA_COLLECTION_PCDT,
    DEFAULT_ADD_BATCH_SIZE,
    DEFAULT_OLLAMA_BASE_URL,
    build_ollama_embeddings,
    embed_one_stem,
    filter_pcdt_chunk_manifest_rows,
    mtime_unchanged_vs_embed_manifest,
    open_chroma_vectorstore,
)
from pcdt_ingest.logutil import configure_logging, get_logger
from pcdt_ingest.manifest import now_iso, read_jsonl, write_jsonl
from pcdt_ingest.paths import (
    DIR_MANIFESTS,
    MANIFEST_PCDT_CHUNK,
    MANIFEST_PCDT_EMBED,
    data_root,
    ensure_data_dirs,
    vectorstore_chroma_dir,
)

_log = get_logger("cli_embed")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Lê llm/data/manifests/pcdt_chunk_index.jsonl, filtra entradas ok/skipped com "
            ".chunks.jsonl existente e grava embeddings no Chroma em vectorstore/chroma/ "
            "(persistente na raiz do repositório)."
        ),
        epilog=(
            "Variável de ambiente opcional: OLLAMA_BASE_URL — URL base do servidor Ollama "
            f"(por omissão {DEFAULT_OLLAMA_BASE_URL})."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Reindexa todos os stems selecionados (ignora manifesto de embed e mtimes).",
    )
    p.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Processa no máximo N documentos (ordem por source_stem).",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_ADD_BATCH_SIZE,
        metavar="N",
        help="Documentos por lote ao chamar o vector store.",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help="Reservado para consistência com outros CLIs; nesta versão o indexação é sequencial.",
    )
    p.add_argument(
        "--skip-embed-manifest",
        action="store_true",
        help="Não lê nem grava manifests/pcdt_embed_index.jsonl (desativa incremental).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Menos saída no console (só avisos e erros).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Registra cada chunk (id, stem, tokens_embed da resposta Ollama) e confirmação "
            "por lote persistido no Chroma."
        ),
    )
    return p.parse_args(argv)


def _load_embed_index_by_stem(path: Path) -> dict[str, dict]:
    rows = read_jsonl(path)
    by_stem: dict[str, dict] = {}
    for row in rows:
        stem = row.get("source_stem")
        if isinstance(stem, str) and stem:
            by_stem[stem] = row
    return by_stem


def _merge_embed_rows(
    existing: dict[str, dict],
    updates: dict[str, dict],
) -> list[dict]:
    merged = {**existing, **updates}
    return [merged[k] for k in sorted(merged.keys())]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.workers < 1:
        print("Erro: --workers deve ser >= 1.", file=sys.stderr)
        return 2
    if args.workers > 1:
        _log.warning(
            "build-vectorstore ignora paralelismo entre stems (--workers=%s); "
            "usa sequencial para evitar condições de corrida no Chroma/Ollama.",
            args.workers,
        )
    if args.batch_size < 1:
        print("Erro: --batch-size deve ser >= 1.", file=sys.stderr)
        return 2
    if args.verbose and args.quiet:
        _log.warning("--verbose e --quiet: mantém nível INFO para os registos detalhados.")

    configure_logging(quiet=args.quiet, verbose=args.verbose)
    ensure_data_dirs()
    root = data_root()
    chroma_dir = vectorstore_chroma_dir()
    chroma_dir.mkdir(parents=True, exist_ok=True)

    chunk_manifest_path = root / DIR_MANIFESTS / MANIFEST_PCDT_CHUNK
    if not chunk_manifest_path.is_file():
        print(f"Manifesto de chunks não encontrado: {chunk_manifest_path}", file=sys.stderr)
        return 1

    raw_rows = read_jsonl(chunk_manifest_path)
    candidates = filter_pcdt_chunk_manifest_rows(raw_rows, root)
    candidates.sort(key=lambda r: str(r.get("source_stem", "")))

    embed_manifest_path = root / DIR_MANIFESTS / MANIFEST_PCDT_EMBED
    embed_by_stem: dict[str, dict] = {}
    if not args.skip_embed_manifest and embed_manifest_path.is_file():
        embed_by_stem = _load_embed_index_by_stem(embed_manifest_path)

    work: list[dict] = []
    for row in candidates:
        stem = row.get("source_stem")
        rel = row.get("chunks_jsonl_relative_path")
        if not isinstance(stem, str) or not isinstance(rel, str):
            continue
        chunks_path = (root / rel).resolve()
        if not chunks_path.is_file():
            continue
        mtime = chunks_path.stat().st_mtime
        if not args.force and not args.skip_embed_manifest:
            prev = embed_by_stem.get(stem)
            if prev and prev.get("status") in ("embedded", "skipped_empty"):
                if mtime_unchanged_vs_embed_manifest(prev.get("chunks_mtime_unix"), mtime):
                    continue
        work.append(row)

    if args.max_files is not None:
        work = work[: max(0, args.max_files)]

    if not work:
        print("Nada a indexar (lista vazia após filtros ou já atualizado).", file=sys.stderr)
        return 0

    embeddings = build_ollama_embeddings()
    store = open_chroma_vectorstore(
        persist_directory=chroma_dir,
        embedding_function=embeddings,
        collection_name=CHROMA_COLLECTION_PCDT,
    )

    updates: dict[str, dict] = {}
    n_emb = n_skip = n_err = 0
    ts_base = now_iso()

    for row in work:
        stem = str(row.get("source_stem"))
        rel = str(row.get("chunks_jsonl_relative_path"))
        chunks_path = (root / rel).resolve()
        mtime = chunks_path.stat().st_mtime
        record = {
            "source_stem": stem,
            "chunks_jsonl_relative_path": rel,
            "embedded_count": 0,
            "status": "error",
            "embedded_at": ts_base,
            "chunks_mtime_unix": mtime,
        }
        try:
            status, count = embed_one_stem(
                store,
                chunks_path,
                source_stem=stem,
                batch_size=args.batch_size,
                verbose=args.verbose,
                embedding_fn=embeddings,
            )
            record["status"] = status
            record["embedded_count"] = count
            record["embedded_at"] = now_iso()
            if status == "embedded":
                n_emb += 1
            else:
                n_skip += 1
        except Exception as e:
            _log.exception("Falha ao indexar %s", stem)
            record["error"] = str(e)
            record["embedded_at"] = now_iso()
            n_err += 1
        updates[stem] = record

    if not args.skip_embed_manifest:
        merged = _merge_embed_rows(embed_by_stem, updates)
        write_jsonl(embed_manifest_path, merged)
        _log.info("Manifesto de embed: %s", embed_manifest_path)

    print(
        f"Concluído. embedded={n_emb} skipped_empty={n_skip} error={n_err}. "
        f"Chroma: {chroma_dir} (coleção {CHROMA_COLLECTION_PCDT})."
    )
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
