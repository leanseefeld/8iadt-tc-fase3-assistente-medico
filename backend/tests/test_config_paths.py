from pathlib import Path

from assistente_medico_api.config import REPO_ROOT, Settings, resolve_chroma_persist_dir


def test_chroma_persist_dir_relative_path_resolves_from_repo_root():
    settings = Settings(chroma_persist_dir=Path("vectorstore/chroma"))

    assert resolve_chroma_persist_dir(settings) == REPO_ROOT / "vectorstore" / "chroma"