"""Resolve caminhos do repositório e de `llm/data`."""

from __future__ import annotations

from pathlib import Path

# --- Segmentos relativos à raiz ``llm/data`` (uso: ``data_root() / DIR_RAW_PCDT``) ---

DIR_RAW_PCDT = Path("raw") / "pcdt"
DIR_RAW_CLINICAL_EXAMS = Path("raw") / "clinical_exams"
DIR_MANIFESTS = Path("manifests")
DIR_PROCESSED_PCDT = Path("processed") / "pcdt"
DIR_CHUNKS_PCDT = Path("chunks") / "pcdt"
DIR_SFT_SAMPLES = Path("sft") / "samples"

DATA_SUBDIRS: tuple[Path, ...] = (
    DIR_RAW_PCDT,
    DIR_RAW_CLINICAL_EXAMS,
    DIR_MANIFESTS,
    DIR_PROCESSED_PCDT,
    DIR_CHUNKS_PCDT,
    DIR_SFT_SAMPLES,
)

# --- Arquivos de manifesto (sob ``DIR_MANIFESTS``) ---

MANIFEST_PCDT_INDEX = "pcdt_index.jsonl"
MANIFEST_PCDT_RUN = "pcdt_run.json"
MANIFEST_CLINICAL_EXAMS_INDEX = "clinical_exams_index.jsonl"
MANIFEST_CLINICAL_EXAMS_RUN = "clinical_exams_run.json"


def find_repo_root() -> Path:
    """A partir de `llm/src/pcdt_ingest/paths.py`, retorna a raiz do repositório."""
    return Path(__file__).resolve().parents[3]


def data_root() -> Path:
    return find_repo_root() / "llm" / "data"


def ensure_data_dirs() -> Path:
    """Cria árvore mínima sob `llm/data`."""
    base = data_root()
    for sub in DATA_SUBDIRS:
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def has_prior_pcdt_run(root: Path | None = None) -> bool:
    """
    Indica se já há artefatos de uma execução PCDT: índice JSONL não vazio
    ou qualquer entrada em ``raw/pcdt``.
    """
    base = root if root is not None else data_root()
    index_path = base / DIR_MANIFESTS / MANIFEST_PCDT_INDEX
    if index_path.is_file() and index_path.stat().st_size > 0:
        return True
    raw = base / DIR_RAW_PCDT
    return raw.is_dir() and any(raw.iterdir())


def has_prior_clinical_exams_run(root: Path | None = None) -> bool:
    """
    Indica se já há artefatos de ingestão Einstein: índice JSONL não vazio
    ou qualquer entrada em ``raw/clinical_exams``.
    """
    base = root if root is not None else data_root()
    index_path = base / DIR_MANIFESTS / MANIFEST_CLINICAL_EXAMS_INDEX
    if index_path.is_file() and index_path.stat().st_size > 0:
        return True
    raw = base / DIR_RAW_CLINICAL_EXAMS
    return raw.is_dir() and any(raw.iterdir())
