"""Resolve caminhos do repositório e de `llm/data`."""

from __future__ import annotations

from pathlib import Path


def find_repo_root() -> Path:
    """A partir de `llm/src/pcdt_ingest/paths.py`, retorna a raiz do repositório."""
    return Path(__file__).resolve().parents[3]


def data_root() -> Path:
    return find_repo_root() / "llm" / "data"


def ensure_data_dirs() -> Path:
    """Cria árvore mínima sob `llm/data`."""
    base = data_root()
    for sub in (
        "raw/pcdt",
        "raw/clinical_exams",
        "manifests",
        "processed/pcdt",
        "chunks/pcdt",
        "sft/samples",
    ):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base
