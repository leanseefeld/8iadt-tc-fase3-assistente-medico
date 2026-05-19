"""Configuração carregada de variáveis de ambiente."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Parâmetros de tempo de execução (prefixo MEDICO_)."""

    model_config = SettingsConfigDict(
        env_prefix="MEDICO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_chat_model: str = "gemma4:e4b-it-q4_K_M"
    chroma_persist_dir: Path | None = Field(
        default=None,
        description="Se None, usa vectorstore/chroma na raiz do repositório (via pcdt_ingest.paths).",
    )
    chroma_collection: str = "pcdt"
    retrieval_k: int = 6
    database_url: str = "sqlite+aiosqlite:///./assistente_medico.db"
    uploads_dir: Path = Field(
        default=Path("./uploads"),
        description="Diretório para uploads manuais de exames.",
    )
    llm_stream_timeout_s: float = Field(
        default=120.0,
        description="Timeout (segundos) para o streaming do nó de geração via Ollama.",
    )

def resolve_runtime_path(path: Path) -> Path:
    """Resolve paths relativos da configuração a partir da raiz do repositório."""
    return path if path.is_absolute() else REPO_ROOT / path


def resolve_chroma_persist_dir(settings: Settings) -> Path:
    """Retorna o diretório Chroma efetivo usado pelo backend."""
    if settings.chroma_persist_dir is not None:
        return resolve_runtime_path(settings.chroma_persist_dir)

    from pcdt_ingest.paths import vectorstore_chroma_dir

    return vectorstore_chroma_dir()