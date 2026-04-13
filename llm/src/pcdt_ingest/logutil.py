"""Configuração de logging para o CLI e o grafo."""

from __future__ import annotations

import logging
import sys


class _FlushingStderrHandler(logging.StreamHandler):
    """Emite no stderr e força flush (útil quando stdout está bufferizado ou em piped terminals)."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def configure_logging(*, quiet: bool = False, verbose: bool = False) -> None:
    """Define formato e nível; idempotente se handlers já existirem no logger raiz."""
    # --verbose força INFO (detalhe por chunk) mesmo com --quiet.
    if verbose:
        level = logging.INFO
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.INFO
    root = logging.getLogger("pcdt_ingest")
    root.setLevel(level)
    if not root.handlers:
        h = _FlushingStderrHandler()
        h.setLevel(level)
        h.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(h)
    else:
        for h in root.handlers:
            h.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Logger filho de `pcdt_ingest.*` para manter o mesmo handler."""
    return logging.getLogger(f"pcdt_ingest.{name}")
