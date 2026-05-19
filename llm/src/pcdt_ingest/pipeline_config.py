"""Carrega a configuração da pipeline RAG definida em ``llm/config.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_root_config() -> ModuleType | None:
    config_path = Path(__file__).resolve().parents[2] / "config.py"
    if not config_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("llm_pipeline_config", config_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CONFIG = _load_root_config()


def get_config(name: str, default: Any) -> Any:
    if _CONFIG is None:
        return default
    return getattr(_CONFIG, name, default)
