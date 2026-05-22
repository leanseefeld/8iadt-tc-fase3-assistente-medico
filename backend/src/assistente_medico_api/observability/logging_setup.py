"""Configura handlers JSON (stdout + arquivo rotativo) para o pacote `assistente_medico`."""

from __future__ import annotations

import logging
import logging.handlers
import threading
from pathlib import Path

from assistente_medico_api.config import Settings, resolve_runtime_path
from assistente_medico_api.observability.json_formatter import JsonFormatter

_CONFIGURED = False
_CONFIGURE_LOCK = threading.Lock()

# Tamanho/arquivos de backup alinhados ao plano (≈5 MB, histórico curto).
_ROTATE_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5


def _parse_level(name: str) -> int:
    level = getattr(logging, str(name).upper(), None)
    return int(level) if isinstance(level, int) else logging.INFO


def configure_logging(settings: Settings) -> None:
    """
    Instala formatter JSON no logger pai `assistente_medico` (uma vez por processo).
    """
    global _CONFIGURED
    with _CONFIGURE_LOCK:
        if _CONFIGURED:
            return

        formatter = JsonFormatter()

        root_med = logging.getLogger("assistente_medico")
        root_med.handlers.clear()
        root_med.setLevel(_parse_level(settings.log_level))
        root_med.propagate = False

        log_dir = resolve_runtime_path(settings.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "assistente_medico.jsonl"
        fh = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=_ROTATE_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        root_med.addHandler(fh)

        # O classificador/regeneração do guardrail emite DEBUG quando passa "seguro".
        logging.getLogger("assistente_medico.audit.rag").setLevel(logging.DEBUG)
        # Mantém o fluxo HTTP legível sem access log duplicado linha a linha.
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

        # Remove handlers legados do guardrail (passa a usar o logger pai).
        gr = logging.getLogger("assistente_medico.guardrail")
        gr.handlers.clear()
        gr.propagate = True

        _CONFIGURED = True
