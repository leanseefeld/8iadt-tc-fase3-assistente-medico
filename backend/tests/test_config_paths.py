from pathlib import Path

from assistente_medico_api.config import (
    BACKEND_ROOT,
    REPO_ROOT,
    Settings,
    resolve_chroma_persist_dir,
    resolve_database_url,
)


def test_chroma_persist_dir_relative_path_resolves_from_repo_root():
    settings = Settings(chroma_persist_dir=Path("vectorstore/chroma"))

    assert resolve_chroma_persist_dir(settings) == REPO_ROOT / "vectorstore" / "chroma"


def test_sqlite_database_url_relative_path_resolves_from_backend_root():
    settings = Settings(database_url="sqlite+aiosqlite:///./assistente_medico.db")

    assert resolve_database_url(settings) == (
        f"sqlite+aiosqlite:///{BACKEND_ROOT / 'assistente_medico.db'}"
    )
