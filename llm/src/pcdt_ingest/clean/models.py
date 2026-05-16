"""Modelos simples para a etapa de limpeza PCDT."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

DocumentClass = Literal["pcdt_completo", "pcdt_resumido_visual", "desconhecido"]


@dataclass(frozen=True)
class CleanConfig:
    """Parâmetros ajustáveis das heurísticas de limpeza."""

    header_footer_threshold: float = 0.5
    header_footer_window: int = 2
    min_words: int = 6
    skip_initial_admin_pages: bool = True


@dataclass
class CleanStats:
    """Resumo acumulável para CLI e dry-run."""

    pages_analyzed: int = 0
    pages_written: int = 0
    pages_skipped: int = 0
    lines_removed: int = 0
    placeholders_removed: int = 0
    signatures_removed: int = 0
    headers_footers_removed: int = 0
    page_numbers_removed: int = 0
    junk_detected: int = 0
    dehyphenated_pages: int = 0

    def merge(self, other: CleanStats) -> None:
        for name in self.__dataclass_fields__:
            setattr(self, name, int(getattr(self, name)) + int(getattr(other, name)))

    def as_dict(self) -> dict[str, int]:
        return {name: int(getattr(self, name)) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class PageCleanResult:
    """Resultado de limpeza de uma página."""

    record: dict[str, Any]
    original_markdown: str
    cleaned_markdown: str
    flags: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None
    stats: CleanStats = field(default_factory=CleanStats)
