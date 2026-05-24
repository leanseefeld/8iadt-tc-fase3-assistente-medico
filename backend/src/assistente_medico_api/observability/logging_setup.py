"""Configura logging leve para o pacote `assistente_medico` (consola apenas)."""

from __future__ import annotations

import logging
import threading

from assistente_medico_api.config import Settings, resolve_runtime_path

_CONFIGURED = False
_CONFIGURE_LOCK = threading.Lock()


def _parse_level(name: str) -> int:
    level = getattr(logging, str(name).upper(), None)
    return int(level) if isinstance(level, int) else logging.INFO


def configure_logging(settings: Settings) -> None:
    """
    Instala formatter simples no logger pai `assistente_medico`.

    A auditoria clínica não usa este canal — grava em `logs/audit_clinical_*.jsonl`.
    Garante apenas que o diretório de logs exista para o escritor clínico.
    """
    global _CONFIGURED
    with _CONFIGURE_LOCK:
        if _CONFIGURED:
            return

        log_dir = resolve_runtime_path(settings.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        root_med = logging.getLogger("assistente_medico")
        root_med.handlers.clear()
        root_med.setLevel(_parse_level(settings.log_level))
        root_med.propagate = False

        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
        root_med.addHandler(sh)

        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

        gr = logging.getLogger("assistente_medico.guardrail")
        gr.handlers.clear()
        gr.propagate = True

        _CONFIGURED = True
