#!/usr/bin/env python3
"""
Estatísticas de tokens por documento PCDT no Chroma.

Para cada PCDT na coleção exibe: número de chunks, total de tokens estimados
e média de tokens por chunk.

Duas estratégias de contagem (flag --tokenizer):
  chars  — estimativa por caracteres (padrão; usa CHARS_PER_TOKEN=4 do config)
  tiktoken — usa tiktoken cl100k_base; requer: pip install tiktoken

Uso:
    cd llm
    python scripts/chroma_token_stats.py
    python scripts/chroma_token_stats.py --tokenizer tiktoken
    python scripts/chroma_token_stats.py --sort chunks
    python scripts/chroma_token_stats.py --collection pcdt --chroma-dir ../vectorstore/chroma
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Resolve repo root so the script works from any CWD
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent  # llm/scripts/ → llm/ → repo root

sys.path.insert(0, str(_SCRIPT_DIR.parent / "src"))

from pcdt_ingest.pipeline_config import get_config  # noqa: E402  (after sys.path patch)
from pcdt_ingest.paths import vectorstore_chroma_dir  # noqa: E402


# ---------------------------------------------------------------------------
# Tokenizer factories
# ---------------------------------------------------------------------------

def _make_char_tokenizer(chars_per_token: int) -> Callable[[str], int]:
    """Estimativa baseada em caracteres — rápida, sem dependências extras."""
    def count(text: str) -> int:
        return max(1, len(text) // chars_per_token)
    return count


def _make_tiktoken_tokenizer() -> Callable[[str], int]:
    """Tokenizador BPE (cl100k_base) — mais preciso, requer 'tiktoken'."""
    try:
        import tiktoken
    except ImportError:
        print(
            "ERRO: tiktoken não está instalado.\n"
            "      Instale com:  pip install tiktoken\n"
            "      Ou use o padrão:  --tokenizer chars",
            file=sys.stderr,
        )
        sys.exit(1)

    enc = tiktoken.get_encoding("cl100k_base")

    def count(text: str) -> int:
        return len(enc.encode(text))

    return count


# ---------------------------------------------------------------------------
# Core stats computation
# ---------------------------------------------------------------------------

def compute_stats(
    collection,
    count_tokens: Callable[[str], int],
) -> dict[str, dict]:
    """
    Lê todos os documentos da coleção e agrega por source_stem.

    Retorna dict stem → {"chunks": int, "total_tokens": int}.
    """
    # Pega documentos e metadados em lote único (sem embeddings para ser rápido)
    result = collection.get(include=["documents", "metadatas"])

    documents: list[str] = result["documents"] or []
    metadatas: list[dict] = result["metadatas"] or []

    if not documents:
        return {}

    # Agrega por stem
    stats: dict[str, dict] = defaultdict(lambda: {"chunks": 0, "total_tokens": 0})

    for text, meta in zip(documents, metadatas):
        stem = (meta or {}).get("source_stem", "<sem source_stem>")
        stats[stem]["chunks"] += 1
        stats[stem]["total_tokens"] += count_tokens(text or "")

    return dict(stats)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_SORT_KEYS = {
    "stem":   lambda item: item[0].lower(),
    "chunks": lambda item: item[1]["chunks"],
    "tokens": lambda item: item[1]["total_tokens"],
    "avg":    lambda item: item[1]["total_tokens"] / max(1, item[1]["chunks"]),
}

COL_STEM   = 50
COL_CHUNKS =  7
COL_TOTAL  = 13
COL_AVG    = 12


def _header() -> str:
    return (
        f"{'PCDT (source_stem)':<{COL_STEM}}"
        f"{'Chunks':>{COL_CHUNKS}}"
        f"{'Total tokens':>{COL_TOTAL}}"
        f"{'Avg tok/chunk':>{COL_AVG}}"
    )


def _row(stem: str, chunks: int, total: int) -> str:
    avg = total / chunks if chunks else 0
    return (
        f"{stem:<{COL_STEM}}"
        f"{chunks:>{COL_CHUNKS},}"
        f"{total:>{COL_TOTAL},}"
        f"{avg:>{COL_AVG}.1f}"
    )


def _separator() -> str:
    return "-" * (COL_STEM + COL_CHUNKS + COL_TOTAL + COL_AVG)


def print_table(
    stats: dict[str, dict],
    sort_by: str,
    reverse: bool,
    tokenizer_label: str,
) -> None:
    """Imprime a tabela formatada no stdout."""
    sorted_items = sorted(stats.items(), key=_SORT_KEYS[sort_by], reverse=reverse)

    grand_chunks = sum(v["chunks"] for v in stats.values())
    grand_tokens = sum(v["total_tokens"] for v in stats.values())

    sep = _separator()

    print(f"\nEstatísticas de tokens — coleção PCDT  (tokenizador: {tokenizer_label})")
    print(sep)
    print(_header())
    print(sep)

    for stem, data in sorted_items:
        print(_row(stem, data["chunks"], data["total_tokens"]))

    # Grand-total row
    print(sep)
    print(_row("TOTAL", grand_chunks, grand_tokens))
    print(sep)
    print(f"\n{len(stats)} documentos · {grand_chunks:,} chunks · {grand_tokens:,} tokens estimados")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    default_chroma = str(vectorstore_chroma_dir())
    default_collection = get_config("CHROMA_COLLECTION_PCDT", "pcdt")

    p = argparse.ArgumentParser(
        description="Estatísticas de tokens por PCDT no vector store Chroma.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--chroma-dir",
        default=default_chroma,
        help="Diretório persistente do Chroma.",
    )
    p.add_argument(
        "--collection",
        default=default_collection,
        help="Nome da coleção Chroma.",
    )
    p.add_argument(
        "--tokenizer",
        choices=["chars", "tiktoken"],
        default="chars",
        help="Estratégia de contagem de tokens.",
    )
    p.add_argument(
        "--sort",
        choices=list(_SORT_KEYS),
        default="tokens",
        help="Coluna de ordenação.",
    )
    p.add_argument(
        "--asc",
        action="store_true",
        help="Ordenar em ordem crescente (padrão: decrescente).",
    )
    return p


def main() -> None:
    args = build_arg_parser().parse_args()

    # Abre cliente Chroma bruto (sem Ollama — não precisa de embeddings para leitura)
    import chromadb

    chroma_path = Path(args.chroma_dir)
    if not chroma_path.exists():
        print(f"ERRO: diretório Chroma não encontrado: {chroma_path}", file=sys.stderr)
        sys.exit(1)

    client = chromadb.PersistentClient(path=str(chroma_path))

    try:
        collection = client.get_collection(args.collection)
    except Exception as exc:
        print(f"ERRO: não foi possível abrir a coleção '{args.collection}': {exc}", file=sys.stderr)
        sys.exit(1)

    total_in_collection = collection.count()
    print(f"Coleção '{args.collection}' — {total_in_collection:,} chunks no total.")

    if total_in_collection == 0:
        print("Coleção vazia. Rode 'build-vectorstore' primeiro.")
        return

    # Seleciona tokenizador
    chars_per_token: int = get_config("CHARS_PER_TOKEN", 4)
    if args.tokenizer == "tiktoken":
        count_tokens = _make_tiktoken_tokenizer()
        tokenizer_label = "tiktoken cl100k_base"
    else:
        count_tokens = _make_char_tokenizer(chars_per_token)
        tokenizer_label = f"chars ÷ {chars_per_token}"

    stats = compute_stats(collection, count_tokens)

    if not stats:
        print("Nenhum documento encontrado na coleção.")
        return

    print_table(stats, sort_by=args.sort, reverse=not args.asc, tokenizer_label=tokenizer_label)


if __name__ == "__main__":
    main()
