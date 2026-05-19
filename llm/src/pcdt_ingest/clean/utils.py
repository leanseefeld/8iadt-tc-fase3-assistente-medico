"""Utilitários puros para normalização de texto."""

from __future__ import annotations

import re
import unicodedata

_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MANY_BLANK_LINES_RE = re.compile(r"\n{3,}")


def normalize_unicode(text: str) -> str:
    """Normaliza unicode e remove caracteres invisíveis comuns em PDFs."""
    normalized = unicodedata.normalize("NFKC", text)
    return _INVISIBLE_RE.sub("", normalized)


def compact_spaces(text: str) -> str:
    """Compacta espaços horizontais e excesso de linhas vazias preservando parágrafos."""
    lines = [_MULTI_SPACE_RE.sub(" ", line).rstrip() for line in text.splitlines()]
    compacted = "\n".join(lines).strip()
    return _MANY_BLANK_LINES_RE.sub("\n\n", compacted)


def strip_accents(text: str) -> str:
    """Remove acentos para comparação heurística."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_key(text: str) -> str:
    """Chave estável para comparar linhas repetidas."""
    text = strip_accents(normalize_unicode(text)).upper()
    text = re.sub(r"[*_`#>\[\](){}]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -–—:;.,")


def dehyphenate(text: str) -> tuple[str, bool]:
    """
    Junta palavras quebradas por quebra de linha ou ``<br>``.

    Mantém hifens compostos na mesma linha, como ``clínico-cirúrgico``.
    """
    before = text
    text = re.sub(r"(?i)([A-Za-zÀ-ÿ]{2,})-\s*<br\s*/?>\s*([A-Za-zÀ-ÿ]{2,})", r"\1\2", text)
    text = re.sub(r"([A-Za-zÀ-ÿ]{2,})-\s*\n\s*([a-zà-ÿ]{2,})", r"\1\2", text)
    return text, text != before


def normalize_table_breaks(text: str) -> tuple[str, bool]:
    """Melhora tabelas markdown extraídas com ``<br>`` dentro de células."""
    changed = False
    out: list[str] = []
    for line in text.splitlines():
        if "|" in line and "<br" in line.lower():
            original = line
            line = re.sub(r"(?i)([A-Za-zÀ-ÿ]{2,})-\s*<br\s*/?>\s*([A-Za-zÀ-ÿ]{2,})", r"\1\2", line)
            line = re.sub(r"(?i)<br\s*/?>", " ", line)
            line = compact_spaces(line)
            changed = changed or line != original
        out.append(line)
    return "\n".join(out), changed


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-zÀ-ÿ0-9]{2,}", text))