"""Heurísticas puras da limpeza PCDT."""

from __future__ import annotations

from collections import Counter
import re
from typing import Iterable, Sequence

from pcdt_ingest.clean.models import CleanConfig, DocumentClass
from pcdt_ingest.clean.utils import normalize_key, normalize_unicode, word_count

IMAGE_PLACEHOLDER_RE = re.compile(
    r"(picture|intentionally omitted|pixmap|<\s*image|image omitted)",
    re.IGNORECASE,
)
PICTURE_TEXT_START_RE = re.compile(r"start of picture text", re.IGNORECASE)
PICTURE_TEXT_END_RE = re.compile(r"end of picture text", re.IGNORECASE)
PAGE_NUMBER_RE = re.compile(r"^\s*(?:[-–—]?\s*)?\d{1,4}\s*(?:[-–—]?\s*)?$")
MARKDOWN_DECORATION_RE = re.compile(r"[*_`#<>\s]+")

_KNOWN_SIGNATURE_KEYS = {
    normalize_key("MOZART JULIO TABOSA SALES"),
    normalize_key("FERNANDA DE NEGRI"),
    normalize_key("HELVÉCIO MIRANDA MAGALHÃES JÚNIOR"),
    normalize_key("CARLOS AUGUSTO GRABOIS GADELHA"),
}

_ADMIN_ONLY_RE = re.compile(
    r"\b("
    r"minist[eé]rio da sa[uú]de|secretaria de ci[eê]ncia|portaria sectics|"
    r"di[aá]rio oficial|resolve:|esta portaria entra em vigor|"
    r"comiss[aã]o nacional de incorpora[cç][aã]o"
    r")\b",
    re.IGNORECASE,
)
_ADMIN_LINE_RE = re.compile(
    r"\b("
    r"PORTARIA\s+(?:SECTICS|SCTIE|SAS|SAES|GM|MS)(?:/MS)?\b|"
    r"MINIST[EÉ]RIO DA SA[ÚU]DE\b|"
    r"SECRETARIA DE CI[ÊE]NCIA\b|"
    r"DI[ÁA]RIO OFICIAL\b"
    r")",
    re.IGNORECASE,
)
_FIGURE_CAPTION_RE = re.compile(
    r"^\s{0,3}#{0,3}\s*\*{0,2}\s*Figura\s+(?:\d+|[IVXLCDM]+)\b",
    re.IGNORECASE,
)
_TABLE_CAPTION_RE = re.compile(
    r"^\s{0,3}#{0,3}\s*\*{0,2}\s*Quadro\s+\d+\b",
    re.IGNORECASE,
)
_HORIZONTAL_RULE_RE = re.compile(r"^\s{0,3}[-–—_]{5,}\s*$")
_GENERIC_PROTOCOL_HEADER_RE = re.compile(
    r"^\s{0,3}#{0,3}\s*\*{0,2}\s*Protocolos?\s+Cl[ií]nicos?\s+e\s+Diretrizes\s+Terap[eê]uticas\s*\*{0,2}\s*$",
    re.IGNORECASE,
)
_FORM_START_RE = re.compile(
    r"(TERMO DE ESCLARECIMENTO E RESPONSABILIDADE|"
    r"FICHA FARMACOTERAP[EÊ]UTICA|"
    r"DADOS DO PACIENTE|"
    r"AVALIA[CÇ][AÃ]O FARMACOTERAP[EÊ]UTICA|"
    r"Eu,\s*_{5,}.*declaro)",
    re.IGNORECASE,
)
_SEARCH_STRATEGY_RE = re.compile(r"estrat[eé]gia de busca|resultados encontrados|bases de dados", re.IGNORECASE)
_SEARCH_STRATEGY_CAPTION_RE = re.compile(r"\bQuadro\b.*estrat[eé]gia de busca", re.IGNORECASE)

_CLINICAL_START_RE = re.compile(
    r"\b(ANEXO|PROTOCOLO CL[IÍ]NICO|DIRETRIZES TERAP[EÊ]UTICAS|1\.\s*INTRODU[CÇ][AÃ]O|INTRODU[CÇ][AÃ]O)\b",
    re.IGNORECASE,
)
_CLINICAL_START_STRONG_RE = re.compile(
    r"(^\s{0,3}#{0,3}\s*\*{0,2}\s*ANEXO\b|"
    r"^\s{0,3}#{0,3}\s*\*{0,2}\s*(?:ANEXO\s+)?PROTOCOLO CL[IÍ]NICO\b|"
    r"^\s{0,3}#{0,3}\s*\*{0,2}\s*1\.\s*INTRODU[CÇ][AÃ]O\b|"
    r"^\s{0,3}#{0,3}\s*\*{0,2}\s*INTRODU[CÇ][AÃ]O\b)",
    re.IGNORECASE | re.MULTILINE,
)

_NUMBERED_SECTION_RE = re.compile(r"^\s{0,3}#{0,3}\s*\*{0,2}\d{1,2}\.\s+[A-ZÀ-Ý0-9]", re.MULTILINE)
_CID_RE = re.compile(r"\bCID(?:-10)?\b|\b[A-Z]\d{2}(?:\.\d)?\b", re.IGNORECASE)
_BULLET_MEDICAL_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S+")


def is_image_placeholder_line(line: str) -> bool:
    return bool(IMAGE_PLACEHOLDER_RE.search(line))


def is_picture_text_start_line(line: str) -> bool:
    return bool(PICTURE_TEXT_START_RE.search(line))


def is_picture_text_end_line(line: str) -> bool:
    return bool(PICTURE_TEXT_END_RE.search(line))


def is_known_signature_line(line: str) -> bool:
    key = normalize_key(line)
    return key in _KNOWN_SIGNATURE_KEYS


def is_page_number_line(line: str) -> bool:
    stripped = MARKDOWN_DECORATION_RE.sub("", line)
    return bool(PAGE_NUMBER_RE.fullmatch(stripped.strip()))


def is_admin_noise_line(line: str) -> bool:
    return bool(_ADMIN_LINE_RE.search(line))


def is_figure_caption_line(line: str) -> bool:
    return bool(_FIGURE_CAPTION_RE.search(line.strip()))


def is_table_caption_line(line: str) -> bool:
    return bool(_TABLE_CAPTION_RE.search(line.strip()))


def is_search_strategy_caption_line(line: str) -> bool:
    return bool(_SEARCH_STRATEGY_CAPTION_RE.search(line.strip()))


def is_horizontal_rule_line(line: str) -> bool:
    return bool(_HORIZONTAL_RULE_RE.fullmatch(line.strip()))


def is_generic_protocol_header_line(line: str) -> bool:
    return bool(_GENERIC_PROTOCOL_HEADER_RE.fullmatch(line.strip()))


def is_form_start_line(line: str) -> bool:
    return bool(_FORM_START_RE.search(line))


def is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def is_empty_or_separator_table_line(line: str) -> bool:
    """Remove linhas de tabela sem conteúdo semântico para RAG."""
    if not is_table_line(line):
        return False
    cells = [cell.strip() for cell in line.strip().split("|")[1:-1]]
    if not cells:
        return False
    return all(not cell or re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def is_malformed_table_block(lines: Sequence[str]) -> bool:
    table_lines = [line.strip() for line in lines if is_table_line(line)]
    if len(table_lines) < 3:
        return False
    joined = "\n".join(table_lines)
    if _SEARCH_STRATEGY_RE.search(joined):
        return True

    cells: list[str] = []
    for line in table_lines:
        parts = line.split("|")
        cells.extend(cell.strip() for cell in parts[1:-1])
    if not cells:
        return False

    empty_cells = sum(1 for cell in cells if not cell)
    avg_cells = len(cells) / max(1, len(table_lines))
    empty_ratio = empty_cells / len(cells)

    data_cells = [cell for cell in cells if cell and not re.fullmatch(r":?-{3,}:?", cell)]
    short_fragments = 0
    for cell in data_cells:
        normalized = normalize_key(cell)
        words = word_count(normalized)
        alnum = sum(ch.isalnum() for ch in normalized)
        if 0 < alnum <= 8 and words <= 1 and normalized not in {"X", "SIM", "NAO", "NÃO"}:
            short_fragments += 1
    fragment_ratio = short_fragments / max(1, len(data_cells))

    return (avg_cells >= 5 and empty_ratio >= 0.35) or fragment_ratio >= 0.30


def is_useful_title(line: str) -> bool:
    """Preserva títulos clínicos curtos e linhas médicas válidas."""
    raw = line.strip()
    key = normalize_key(raw)
    if not raw:
        return False
    if raw.startswith("#"):
        return True
    if _CLINICAL_START_RE.search(raw):
        return True
    if _NUMBERED_SECTION_RE.search(raw):
        return True
    if _CID_RE.search(raw):
        return True
    if _BULLET_MEDICAL_RE.search(raw):
        return True
    clinical_terms = (
        "DIAGNÓSTICO",
        "DIAGNOSTICO",
        "TRATAMENTO",
        "MONITORAMENTO",
        "CRITÉRIOS",
        "CRITERIOS",
        "INCLUSÃO",
        "INCLUSAO",
        "EXCLUSÃO",
        "EXCLUSAO",
        "CASOS ESPECIAIS",
        "REFERÊNCIAS",
        "REFERENCIAS",
    )
    return any(term in key for term in clinical_terms)


def repeated_edge_line_keys(
    pages: Sequence[str],
    *,
    threshold: float,
    window: int = 2,
) -> set[str]:
    """Detecta headers/footers repetidos nas primeiras/últimas linhas não vazias."""
    if len(pages) < 3:
        return set()
    counts: Counter[str] = Counter()
    for text in pages:
        nonempty = [line.strip() for line in text.splitlines() if line.strip()]
        edge_lines = nonempty[:window] + nonempty[-window:]
        for line in edge_lines:
            key = normalize_key(line)
            looks_like_body = word_count(line) >= 3 and any(ch.islower() for ch in line) and line.rstrip().endswith(".")
            if key and not looks_like_body and not is_useful_title(line):
                counts[key] += 1
    min_count = int(len(pages) * threshold) + 1
    return {key for key, count in counts.items() if count >= min_count}


def is_junk_text(text: str, *, min_words: int = 6) -> bool:
    """Identifica texto sem valor semântico para RAG clínico."""
    normalized = normalize_unicode(text).strip()
    if not normalized:
        return True
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if lines and all(is_image_placeholder_line(line) or is_known_signature_line(line) for line in lines):
        return True
    if any(is_useful_title(line) for line in lines):
        return False
    words = word_count(normalized)
    if words < min_words:
        return True
    alnum = sum(ch.isalnum() for ch in normalized)
    visible = sum(not ch.isspace() for ch in normalized)
    if visible and (alnum / visible) < 0.35:
        return True
    if words < 35 and _ADMIN_ONLY_RE.search(normalized):
        return True
    return False


def find_clinical_content_start_page(pages: Sequence[dict[str, object] | str]) -> int:
    """
    Retorna a página 1-based onde o conteúdo clínico parece começar.

    Se nada for encontrado, retorna a primeira página disponível.
    """
    first_page = 1
    for i, item in enumerate(pages):
        if isinstance(item, dict):
            page = int(item.get("page") or i + 1)
            text = str(item.get("markdown") or "")
        else:
            page = i + 1
            text = str(item)
        if i == 0:
            first_page = page
        if _CLINICAL_START_STRONG_RE.search(text):
            return page
    return first_page


def classify_document(texts: Iterable[str]) -> DocumentClass:
    joined = "\n".join(texts)
    if not joined.strip():
        return "desconhecido"
    image_hits = len(IMAGE_PLACEHOLDER_RE.findall(joined))
    numbered_sections = len(_NUMBERED_SECTION_RE.findall(joined))
    has_annex = bool(re.search(r"\bANEXO\b", joined, re.IGNORECASE))
    has_protocol = bool(re.search(r"PROTOCOLO CL[IÍ]NICO|DIRETRIZES TERAP[EÊ]UTICAS", joined, re.IGNORECASE))
    words = word_count(joined)
    lines = [line.strip() for line in joined.splitlines() if line.strip()]
    short_lines = sum(1 for line in lines if word_count(line) <= 5)
    short_ratio = short_lines / max(1, len(lines))

    if has_annex and has_protocol and numbered_sections >= 2 and words >= 250:
        return "pcdt_completo"
    if image_hits >= 3 or (len(lines) >= 4 and words < 350 and short_ratio > 0.65):
        return "pcdt_resumido_visual"
    return "desconhecido"


def line_skip_reason(line: str, repeated_keys: set[str]) -> str | None:
    key = normalize_key(line)
    if is_image_placeholder_line(line):
        return "image_placeholder"
    if is_known_signature_line(line):
        return "signature"
    if is_page_number_line(line):
        return "page_number"
    if is_admin_noise_line(line):
        return "admin_noise"
    if is_figure_caption_line(line):
        return "figure_caption"
    if is_search_strategy_caption_line(line):
        return "search_strategy_caption"
    if is_table_line(line) and _SEARCH_STRATEGY_RE.search(line):
        return "search_strategy_table_row"
    if is_empty_or_separator_table_line(line):
        return "empty_table_row"
    if is_horizontal_rule_line(line):
        return "horizontal_rule"
    if is_generic_protocol_header_line(line):
        return "generic_protocol_header"
    if key in repeated_keys and not is_useful_title(line):
        return "header_footer"
    return None


def cleaning_flag_for_reason(reason: str) -> str:
    return {
        "image_placeholder": "removed_image_placeholder",
        "signature": "removed_signature",
        "page_number": "removed_page_number",
        "header_footer": "removed_header_footer",
        "admin_noise": "removed_admin_noise",
        "figure_caption": "removed_figure_caption",
        "picture_text_block": "removed_picture_text_block",
        "horizontal_rule": "removed_horizontal_rule",
        "generic_protocol_header": "removed_generic_protocol_header",
        "form_block": "removed_form_block",
        "malformed_table": "removed_malformed_table",
        "search_strategy_caption": "removed_search_strategy_caption",
        "search_strategy_table_row": "removed_search_strategy_table_row",
        "empty_table_row": "removed_empty_table_row",
    }[reason]


def default_config(
    *,
    header_footer_threshold: float = 0.5,
    min_words: int = 6,
) -> CleanConfig:
    return CleanConfig(
        header_footer_threshold=header_footer_threshold,
        min_words=min_words,
    )
