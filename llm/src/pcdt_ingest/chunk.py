"""Fragmentação de sidecars ``*.pages.jsonl`` em chunks com metadata (seção, páginas)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

# Sentence tokenizer: prefer nltk.sent_tokenize when available, fallback to regex
try:
    import nltk  # type: ignore
    from nltk.tokenize import sent_tokenize as _nltk_sent_tokenize  # type: ignore
    try:
        nltk.data.find("tokenizers/punkt")
    except Exception:
        # best-effort download; if it fails, we'll fallback to regex below
        try:
            nltk.download("punkt")
        except Exception:
            pass

    def _sent_tokenize(text: str) -> list[str]:
        return _nltk_sent_tokenize(text)

except Exception:
    def _sent_tokenize(text: str) -> list[str]:
        # simple regex fallback: split after sentence-ending punctuation
        parts = re.split(r'(?<=[.!?…])\s+', text)
        return [p for p in parts if p.strip()]


from pcdt_ingest.clean.cleaner import CLEANED_PAGE_JSONL_SUFFIX, default_cleaned_processed_dir
from pcdt_ingest.extract import PAGE_JSONL_SUFFIX, PageRecord, read_pages_jsonl
from pcdt_ingest.logutil import get_logger
from pcdt_ingest.paths import DIR_RAW_PCDT, DIR_CHUNKS_PCDT, data_root
from pcdt_ingest.pipeline_config import get_config
from pcdt_ingest.reference_data.conitec_catalog import (
    heuristic_metadata,
    match_source_to_disease,
    metadata_from_catalog_entry,
)

_log = get_logger("chunk")

_CHARS_PER_TOKEN = int(get_config("CHARS_PER_TOKEN", 4))
_CHUNK_TOKENS = int(get_config("CHUNK_TOKENS", 400))
_OVERLAP_TOKENS = int(get_config("CHUNK_OVERLAP_TOKENS", 50))
_DEFAULT_CHUNK_STRATEGY = str(get_config("CHUNK_STRATEGY", "recursive"))
_DEFAULT_SEMANTIC_BREAKPOINT_PERCENTILE = int(get_config("SEMANTIC_BREAKPOINT_PERCENTILE", 85))

CHUNK_JSONL_SUFFIX = str(get_config("CHUNK_JSONL_SUFFIX", ".chunks.jsonl"))

# Cabeçalhos markdown típicos em PCDT (ajustável).
_DEFAULT_HEADER_SPLITS: list[tuple[str, str]] = [
    ("##", "header_1"),
    ("###", "header_2"),
]

ChunkStrategy = Literal["recursive", "semantic"]

_SEMANTIC_EMBEDDING_MODEL = str(get_config("OLLAMA_EMBED_MODEL", "nomic-embed-text"))
_OLLAMA_BASE_URL = str(get_config("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))

_MAIN_SECTION_TITLES = {
    "INTRODUÇÃO",
    "CLASSIFICAÇÃO ESTATÍSTICA INTERNACIONAL DE DOENÇAS E PROBLEMAS RELACIONADOS À SAÚDE (CID-10)",
    "CLASSIFICAÇÃO ESTATÍSTICA INTERNACIONAL DE DOENÇAS E PROBLEMAS RELACIONADOS A SAÚDE (CID-10)",
    "CLASSIFICAÇÃO ESTATÍSTICA INTERNACIONAL DE DOENÇAS E PROBLEMAS RELACIONADOS À SAÚDE",
    "CLASSIFICAÇÃO ESTATÍSTICA INTERNACIONAL DE DOENÇAS E PROBLEMAS RELACIONADOS A SAÚDE",
    "DIAGNÓSTICO",
    "CRITÉRIOS DE INCLUSÃO",
    "CRITÉRIOS DE EXCLUSÃO",
    "CASOS ESPECIAIS",
    "TRATAMENTO",
    "MONITORAMENTO",
    "REGULAÇÃO/CONTROLE/AVALIAÇÃO PELO GESTOR",
    "TERMO DE ESCLARECIMENTO E RESPONSABILIDADE",
    "REFERÊNCIAS",
    "ANEXO",
    "APÊNDICE",
}

_TITLE_REGEXES = [
    re.compile(
        r"\bProtocolo\s+Cl[iíÍ]nico\s+e\s+Diretrizes\s+Terap[eéêÉÊ]uticas\s+d(?:a|e|o|as|os)\s+(.+?)(?:\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bProtocolo\s+Cl[iíÍ]nico\s+e\s+Diretrizes\s+Terap[eéêÉÊ]uticas\s+(?:[-–—]\s*)?(.+?)(?:\n|$)",
        re.IGNORECASE,
    ),
    re.compile(r"\bPCDT\s+d(?:a|e|o|as|os)\s+(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"\bDiretrizes\s+Terap[eéêÉÊ]uticas\s+d(?:a|e|o|as|os)\s+(.+?)(?:\n|$)", re.IGNORECASE),
]


def stitch_with_page_spans(
    pages: list[PageRecord],
) -> tuple[str, list[tuple[int, int, int]]]:
    """
    Concatena páginas com ``\\n\\n`` e regista intervalos globais [start, end) por página.
    """
    if not pages:
        return "", []
    pieces: list[str] = []
    spans: list[tuple[int, int, int]] = []
    offset = 0
    for i, rec in enumerate(pages):
        if i > 0:
            offset += 2  # ``\\n\\n`` entre páginas
        start = offset
        text = rec.markdown
        end = start + len(text)
        spans.append((start, end, rec.page))
        offset = end
        pieces.append(text)
    return "\n\n".join(pieces), spans


def page_range_for_char_span(
    spans: list[tuple[int, int, int]],
    gstart: int,
    gend: int,
) -> tuple[int, int]:
    """Devolve (page_start, page_end) inclusivos para o intervalo de caracteres [gstart, gend)."""
    touched: list[int] = []
    for s, e, p in spans:
        if gstart < e and gend > s:
            touched.append(p)
    if not touched:
        return 1, 1
    return min(touched), max(touched)


def _clean_heading_markup(line: str) -> str:
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", line.strip())
    cleaned = re.sub(r"^\*{1,2}|\*{1,2}$", "", cleaned.strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _is_upperish(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    upper = sum(1 for ch in letters if ch.upper() == ch)
    return upper / len(letters) >= 0.80


def _normalized_section_heading(line: str) -> str | None:
    stripped = _clean_heading_markup(line)
    if not stripped or len(stripped) > 120:
        return None
    if stripped.endswith((".", ";", ",")):
        return None

    upper = stripped.upper()
    if upper in {"ANEXO", "APÊNDICE", "APENDICE", "REFERÊNCIAS", "REFERENCIAS"}:
        return f"## {stripped}"

    numbered = re.match(r"^(\d{1,2})(?:\.(\d{1,2}))?\.?\s+(.+)$", stripped)
    if numbered:
        sub_number = numbered.group(2)
        title = numbered.group(3).strip()
        title_upper = title.upper()
        if len(title) > 120 or title.endswith((".", ";", ",")):
            return None
        if title_upper in _MAIN_SECTION_TITLES or _is_upperish(title) or (sub_number and 2 <= len(title.split()) <= 10):
            level = "###" if sub_number else "##"
            return f"{level} {title}"
        return None

    if upper in _MAIN_SECTION_TITLES:
        return f"## {stripped}"

    words = stripped.split()
    if (
        _is_upperish(stripped)
        and 3 <= len(words) <= 18
        and "|" not in stripped
        and not re.search(r"\.{3,}", stripped)
    ):
        return f"## {stripped}"

    return None


def _normalize_pcdt_markdown_headers_with_map(text: str) -> tuple[str, list[int]]:
    out: list[str] = []
    char_map: list[int] = []
    offset = 0
    lines = text.splitlines(keepends=True)

    for line in lines:
        body = line[:-1] if line.endswith("\n") else line
        newline = "\n" if line.endswith("\n") else ""
        replacement = _normalized_section_heading(body)
        emitted = replacement if replacement is not None else body
        out.append(emitted)
        if replacement is None:
            char_map.extend(offset + i for i in range(len(emitted)))
        else:
            source_start = offset + max(0, len(body) - len(body.lstrip()))
            char_map.extend([source_start] * len(emitted))
        if newline:
            out.append(newline)
            char_map.append(offset + len(body))
        offset += len(line)

    return "".join(out), char_map


def normalize_pcdt_markdown_headers(text: str) -> str:
    """Normaliza títulos típicos de PCDT para headings Markdown ``##``/``###``."""
    normalized, _ = _normalize_pcdt_markdown_headers_with_map(text)
    return normalized


def _section_breadcrumb(meta: dict[str, Any]) -> str:
    parts: list[str] = []
    for k in ("header_1", "header_2"):
        v = meta.get(k)
        if v is not None and str(v).strip():
            parts.append(str(v).strip())
    if parts:
        return " > ".join(parts)
    return "(sem cabeçalho)"


def _align_sections_to_full_text(
    full_text: str,
    section_docs: list[Document],
) -> list[tuple[Document, int, int]]:
    """Associa cada seção ao intervalo global [start, end) em ``full_text``."""
    aligned: list[tuple[Document, int, int]] = []
    pos = 0
    for doc in section_docs:
        body = doc.page_content
        if not body:
            aligned.append((doc, pos, pos))
            continue
        idx = full_text.find(body, pos)
        if idx == -1:
            stripped = body.lstrip()
            idx = full_text.find(stripped, pos) if stripped else -1
        if idx == -1:
            idx = pos
        start = idx
        end = start + len(body)
        pos = max(pos, end)
        aligned.append((doc, start, end))
    return aligned


def _map_normalized_span_to_original(char_map: list[int], start: int, end: int) -> tuple[int, int]:
    if not char_map:
        return start, end
    if end <= start:
        idx = min(max(start, 0), len(char_map) - 1)
        return char_map[idx], char_map[idx]
    sidx = min(max(start, 0), len(char_map) - 1)
    eidx = min(max(end - 1, 0), len(char_map) - 1)
    return char_map[sidx], char_map[eidx] + 1


def _find_piece_span(text: str, piece: str, *, search_at: int, overlap: int = 0) -> tuple[int, int, int]:
    idx = text.find(piece, search_at)
    if idx == -1:
        stripped = piece.strip()
        idx = text.find(stripped, search_at) if stripped else -1
        if idx != -1:
            piece = stripped
    if idx == -1:
        idx = search_at
    end = idx + len(piece)
    next_search_at = max(search_at, idx + max(1, len(piece) - overlap))
    return idx, end, next_search_at


def _split_section_recursive(
    section_doc: Document,
    *,
    global_start: int,
    rec: RecursiveCharacterTextSplitter,
    chunk_size: int,
    chunk_overlap: int = 0,
) -> list[tuple[str, dict[str, Any], int, int]]:
    """
    Parte o texto da seção em chunks; devolve lista de
    (texto, metadados base, char_global_start, char_global_end).
    """
    section_text = section_doc.page_content
    base_meta = dict(section_doc.metadata)
    if not section_text.strip():
        return []

    # Primeiro, tente fragmentar respeitando limites de sentença e agrupando
    # sentenças em blocos que caibam em `chunk_size`. Isso evita cortes
    # no meio de uma frase causados pelo Recursive splitter.
    pieces = _group_sentences_into_pieces(section_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    out: list[tuple[str, dict[str, Any], int, int]] = []
    search_at = 0
    if pieces:
        # Mapear cada piece de volta ao texto da seção
        mini_search_at = 0
        for piece in pieces:
            s, e, mini_search_at = _find_piece_span(
                section_text,
                piece,
                search_at=mini_search_at,
                overlap=chunk_overlap,
            )
            out.append((piece, base_meta, global_start + s, global_start + e))
        # aplicar merge adjacente conservador antes de devolver
        return _merge_adjacent_out_items(out)

    # Fallback: ``RecursiveCharacterTextSplitter`` por seção (se tokenizer
    # não produziu bons resultados).
    mini_docs = rec.split_documents([Document(page_content=section_text, metadata=base_meta)])
    overlap = getattr(rec, "chunk_overlap", 0)
    search_at = 0
    for mini in mini_docs:
        piece = mini.page_content
        local_start, local_end, search_at = _find_piece_span(
            section_text,
            piece,
            search_at=search_at,
            overlap=overlap,
        )
        g0 = global_start + local_start
        g1 = global_start + local_end
        out.append((piece, dict(mini.metadata), g0, g1))
    return _merge_adjacent_out_items(out)


def build_semantic_splitter(
    *,
    breakpoint_threshold_amount: int = _DEFAULT_SEMANTIC_BREAKPOINT_PERCENTILE,
    model_name: str = _SEMANTIC_EMBEDDING_MODEL,
    base_url: str = _OLLAMA_BASE_URL,
):
    """Cria ``SemanticChunker`` com os mesmos embeddings Ollama usados na indexação."""
    try:
        from langchain_experimental.text_splitter import SemanticChunker
        from langchain_ollama import OllamaEmbeddings
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Chunking semantic requer a dependência opcional langchain-experimental "
            "e Ollama com o modelo de embedding configurado. Instale com:\n"
            'pip install -e "llm[semantic]"\n'
            f"ollama pull {model_name}"
        ) from exc

    embeddings = OllamaEmbeddings(model=model_name, base_url=base_url)
    return SemanticChunker(
        embeddings,
        breakpoint_threshold_type="percentile",
        breakpoint_threshold_amount=breakpoint_threshold_amount,
    )


def _split_text_with_semantic_splitter(splitter: Any, text: str) -> list[str]:
    if hasattr(splitter, "split_text"):
        chunks = splitter.split_text(text)
        return [str(chunk) for chunk in chunks if str(chunk).strip()]
    docs = splitter.create_documents([text])
    return [str(doc.page_content) for doc in docs if str(doc.page_content).strip()]


def _looks_like_semantic_fragment(text: str, *, min_chars: int) -> bool:
    stripped = text.strip()
    if len(stripped) < min_chars:
        return True
    tail = stripped[-100:]
    if re.search(r"(?:^|\s)_?[A-Z]\.$", tail):
        return True
    if tail.count("_") % 2 == 1:
        return True
    if not re.search(r"[.!?)](?:\s|$)", tail):
        return True
    return False


def _join_semantic_chunks(left: str, right: str) -> str:
    left = left.rstrip()
    right = right.lstrip()
    if not left:
        return right
    if not right:
        return left
    if left.endswith("-"):
        return f"{left}{right}"
    return f"{left} {right}"


def _tail_for_overlap(text: str, overlap: int) -> str:
    if overlap <= 0 or not text:
        return ""
    tail = text[-overlap:].lstrip()
    boundary = re.search(r"(?<=[.!?…])\s+", tail)
    if boundary and boundary.end() < len(tail):
        return tail[boundary.end() :].lstrip()
    space = tail.find(" ")
    if 0 <= space < len(tail) - 1:
        return tail[space + 1 :].lstrip()
    return tail


def _group_sentences_into_pieces(text: str, chunk_size: int, chunk_overlap: int = 0) -> list[str]:
    """Split `text` into sentences and group sentences into pieces <= chunk_size.

    Returns empty list when sentence-based grouping is not applicable (single sentence
    or tokenizer unavailable).
    """
    try:
        sentences = _sent_tokenize(text)
    except Exception:
        return []
    if not sentences or len(sentences) <= 1:
        return []

    pieces: list[str] = []
    buf = ""
    for sent in sentences:
        if not buf:
            buf = sent
            continue
        candidate = _join_semantic_chunks(buf, sent)
        if len(candidate) <= chunk_size:
            buf = candidate
            continue
        pieces.append(buf)
        tail = _tail_for_overlap(buf, min(chunk_overlap, max(0, chunk_size // 2)))
        with_overlap = _join_semantic_chunks(tail, sent) if tail else sent
        buf = with_overlap if len(with_overlap) <= chunk_size + max(0, chunk_overlap) else sent
    if buf:
        pieces.append(buf)
    return pieces


def _merge_semantic_fragments(chunks: list[str], *, chunk_size: int) -> list[str]:
    """Mescla quebras semânticas pequenas ou claramente fraturadas."""
    min_chars = max(280, min(700, chunk_size // 3))
    merged: list[str] = []
    buffer = ""

    for raw in chunks:
        chunk = raw.strip()
        if not chunk:
            continue
        if not buffer:
            buffer = chunk
            continue

        should_merge = (
            _looks_like_semantic_fragment(buffer, min_chars=min_chars)
            or _looks_like_semantic_fragment(chunk, min_chars=min_chars)
        )
        candidate = _join_semantic_chunks(buffer, chunk)
        if should_merge or len(candidate) <= min_chars:
            buffer = candidate
            continue

        merged.append(buffer)
        buffer = chunk

    if buffer:
        merged.append(buffer)
    return merged


def _merge_on_sentence_boundaries(chunks: list[str]) -> list[str]:
    """Mescla quebras entre chunks quando parecem ocorrer no meio de uma frase.

    Regras simples utilizadas:
    - Se o chunk da esquerda termina com pontuação de final de sentença (., !, ?) mantém a quebra.
    - Se o chunk da direita começa com letra minúscula (provável continuação), mescla.
    - Se o buffer atual for muito curto (< 200 chars) mescla com o próximo.
    Essas heurísticas são intencionadas para evitar fragmentos como "disponibilidade de".
    """
    if not chunks:
        return []
    merged: list[str] = []
    buf = chunks[0]
    for nxt in chunks[1:]:
        left = buf.rstrip()
        right = nxt.lstrip()

        # termina explicitly with sentence-ending punctuation (allowing quotes/parens)
        if re.search(r"[\.\!\?…][\"'\)\]]*\s*$", left):
            merged.append(buf)
            buf = nxt
            continue

        # se o próximo começa com letra minúscula, é muito provável continuação
        if right and right[0].islower():
            buf = _join_semantic_chunks(buf, nxt)
            continue

        # se o último token esquerdo é uma preposição comum em português,
        # provavelmente a quebra ocorreu no meio da frase (ex.: "disponibilidade de")
        if re.search(r"\b(?:de|do|da|dos|das|em|no|na|nos|nas|para|por|com|sem|sob|sobre)\s*$", left, flags=re.IGNORECASE):
            buf = _join_semantic_chunks(buf, nxt)
            continue

        # se o buffer for pequeno, prefira juntar para evitar fragmentos curtos
        if len(left) < 200:
            buf = _join_semantic_chunks(buf, nxt)
            continue

        # caso contrário, mantém a quebra
        merged.append(buf)
        buf = nxt

    if buf:
        merged.append(buf)
    return merged


def _split_section_semantic(
    section_doc: Document,
    *,
    global_start: int,
    semantic_splitter: Any,
    rec: RecursiveCharacterTextSplitter,
    chunk_size: int,
) -> list[tuple[str, dict[str, Any], int, int]]:
    section_text = section_doc.page_content
    base_meta = dict(section_doc.metadata)
    if not section_text.strip():
        return []

    try:
        semantic_chunks = _split_text_with_semantic_splitter(semantic_splitter, section_text)
    except Exception as exc:
        _log.warning("SemanticChunker falhou em seção; usando recursive fallback. erro=%s", exc)
        return _split_section_recursive(
            section_doc,
            global_start=global_start,
            rec=rec,
            chunk_size=chunk_size,
            chunk_overlap=getattr(rec, "chunk_overlap", 0),
        )
    semantic_chunks = _merge_semantic_fragments(semantic_chunks, chunk_size=chunk_size)
    # Passe adicional para evitar que quebras semânticas fragmentem frases
    # Ex.: "...disponibilidade de" + "alimentos..." => juntar
    semantic_chunks = _merge_on_sentence_boundaries(semantic_chunks)

    out: list[tuple[str, dict[str, Any], int, int]] = []
    search_at = 0
    for chunk in semantic_chunks:
        if len(chunk) > chunk_size:
            # Primeiro, tente dividir respeitando limites de sentença
            try:
                sentences = _sent_tokenize(chunk)
            except Exception:
                sentences = []

            if sentences and len(sentences) > 1:
                # Agrupa sentenças em blocos que caibam em chunk_size
                pieces: list[str] = []
                buf = ""
                for sent in sentences:
                    if not buf:
                        buf = sent
                        continue
                    # usar _join_semantic_chunks para preservar espaçamento/hífens
                    candidate = _join_semantic_chunks(buf, sent)
                    if len(candidate) <= chunk_size:
                        buf = candidate
                        continue
                    pieces.append(buf)
                    buf = sent
                if buf:
                    pieces.append(buf)

                # Mapear cada piece de volta ao texto da seção
                local_base, _local_end, search_at = _find_piece_span(section_text, chunk, search_at=search_at)
                mini_search_at = 0
                for piece in pieces:
                    s, e, mini_search_at = _find_piece_span(chunk, piece, search_at=mini_search_at)
                    out.append((piece, base_meta, global_start + local_base + s, global_start + local_base + e))
                continue

            # fallback: dividir por rec.split_documents como antes
            mini_docs = rec.split_documents([Document(page_content=chunk, metadata=base_meta)])
            local_base, _local_end, search_at = _find_piece_span(section_text, chunk, search_at=search_at)
            mini_search_at = 0
            for mini in mini_docs:
                piece = mini.page_content
                s, e, mini_search_at = _find_piece_span(chunk, piece, search_at=mini_search_at)
                out.append((piece, dict(mini.metadata), global_start + local_base + s, global_start + local_base + e))
            continue

        local_start, local_end, search_at = _find_piece_span(section_text, chunk, search_at=search_at)
        out.append((chunk, base_meta, global_start + local_start, global_start + local_end))
    # Depois de produzir os blocos, aplica um merge adjacente para juntar
    # quebras que ocorreram dentro de frases após o uso do Recursive splitter.
    return _merge_adjacent_out_items(out)


def _merge_adjacent_out_items(out: list[tuple[str, dict[str, Any], int, int]]) -> list[tuple[str, dict[str, Any], int, int]]:
    """Mescla itens adjacentes da lista `out` quando parecem ser continuação de frase.

    Preserva metadados: só mescla quando metadata é igual (ou suficientemente igual).
    """
    if not out:
        return out
    merged: list[tuple[str, dict[str, Any], int, int]] = []
    cur_text, cur_meta, cur_g0, cur_g1 = out[0]

    def meta_eq(a: dict, b: dict) -> bool:
        # comparador simples: header_1/header_2/page_start/page_end
        keys = ("header_1", "header_2", "page_start", "page_end")
        for k in keys:
            if a.get(k) != b.get(k):
                return False
        return True

    for nxt_text, nxt_meta, nxt_g0, nxt_g1 in out[1:]:
        left = cur_text.rstrip()
        right = nxt_text.lstrip()

        should_merge = False
        # se esquerda termina com pontuação de fim de frase -> não mesclar
        if re.search(r"[.!?…][\"'\)\]]*\s*$", left):
            should_merge = False
        elif right and right[0].islower():
            should_merge = True
        elif len(left) < 200:
            should_merge = True
        elif re.search(r"\b(?:de|do|da|dos|das|em|no|na|nos|nas|para|por|com|sem|sob|sobre)\s*$", left, flags=re.IGNORECASE):
            should_merge = True

        if should_merge and meta_eq(cur_meta, nxt_meta):
            cur_text = _join_semantic_chunks(cur_text, nxt_text)
            cur_g1 = nxt_g1
        else:
            merged.append((cur_text, cur_meta, cur_g0, cur_g1))
            cur_text, cur_meta, cur_g0, cur_g1 = nxt_text, nxt_meta, nxt_g0, nxt_g1

    merged.append((cur_text, cur_meta, cur_g0, cur_g1))
    return merged


def _split_text_strict_with_offsets(text: str, *, max_chars: int) -> list[tuple[str, int, int]]:
    """Divide texto em partes com tamanho máximo rígido, preservando offsets locais aproximados."""
    stripped = text.strip()
    if not stripped:
        return []
    if max_chars < 1 or len(stripped) <= max_chars:
        start = text.find(stripped)
        start = max(0, start)
        return [(stripped, start, start + len(stripped))]

    pieces: list[tuple[str, int, int]] = []
    cursor = 0
    text_len = len(text)
    while cursor < text_len:
        while cursor < text_len and text[cursor].isspace():
            cursor += 1
        if cursor >= text_len:
            break

        hard_end = min(text_len, cursor + max_chars)
        if hard_end >= text_len:
            end = text_len
        else:
            window = text[cursor:hard_end]
            cut = max(
                window.rfind("\n\n"),
                window.rfind(". "),
                window.rfind("; "),
                window.rfind(" | "),
                window.rfind(" "),
            )
            if cut < max_chars * 0.55:
                end = hard_end
            else:
                end = cursor + cut + 1

        piece = text[cursor:end].strip()
        if piece:
            local_start = cursor + max(0, text[cursor:end].find(piece))
            pieces.append((piece, local_start, local_start + len(piece)))
        cursor = max(end, cursor + 1)

    return pieces


def _enforce_chunk_item_limits(
    items: list[tuple[str, dict[str, Any], int, int]],
    *,
    chunk_size: int,
) -> list[tuple[str, dict[str, Any], int, int]]:
    """Garante que nenhum item bruto ultrapasse ``chunk_size`` antes da criação dos Documents."""
    if chunk_size < 1:
        return items
    out: list[tuple[str, dict[str, Any], int, int]] = []
    split_count = 0
    for text, meta, g0, g1 in items:
        if len(text.strip()) <= chunk_size:
            out.append((text, meta, g0, g1))
            continue
        parts = _split_text_strict_with_offsets(text, max_chars=chunk_size)
        split_count += max(0, len(parts) - 1)
        span_len = max(1, g1 - g0)
        text_len = max(1, len(text))
        for piece, local_start, local_end in parts:
            part_g0 = g0 + int(span_len * (local_start / text_len))
            part_g1 = g0 + int(span_len * (local_end / text_len))
            out.append((piece, meta, part_g0, max(part_g0 + 1, part_g1)))
    if split_count:
        _log.info("chunks acima do limite divididos após merge: partes_adicionais=%s limite_chars=%s", split_count, chunk_size)
    return out


def _clean_disease_candidate(value: str) -> str:
    text = re.sub(r"[*_`#]", "", value)
    text = re.sub(r"\([^)]*(?:CID|CONITEC|PCDT)[^)]*\)", "", text, flags=re.IGNORECASE)
    text = re.split(r"\s{2,}|\n|\.|;", text, maxsplit=1)[0]
    text = re.sub(r"\b(?:no|na|para|em)\s+sus\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -–—:,.")
    words = text.split()
    if len(words) > 14:
        text = " ".join(words[:14])
    return text.strip()


def _disease_from_title_text(text: str) -> str | None:
    sample = re.sub(r"[ \t]+", " ", text[:12000])
    for pattern in _TITLE_REGEXES:
        match = pattern.search(sample)
        if not match:
            continue
        candidate = _clean_disease_candidate(match.group(1))
        if candidate and len(candidate) >= 4:
            return candidate
    return None


def _disease_from_standalone_title(text: str) -> str | None:
    for raw in text[:12000].splitlines():
        candidate = _clean_heading_markup(raw)
        if not candidate:
            continue
        upper = candidate.upper()
        if upper in _MAIN_SECTION_TITLES or upper in {"ANEXO", "APÊNDICE", "APENDICE", "REFERÊNCIAS", "REFERENCIAS"}:
            continue
        words = candidate.split()
        if (
            _is_upperish(candidate)
            and 3 <= len(words) <= 18
            and "|" not in candidate
            and not re.search(r"\.{3,}", candidate)
        ):
            return candidate
    return None


def _apply_filename_repairs(text: str) -> str:
    repairs = {
        "deficincia": "deficiencia",
        "deficiênciaferro": "deficiência ferro",
        "deficienciaferro": "deficiencia ferro",
        "doencarenalcronica": "doenca renal cronica",
        "c1esterase": "c1 esterase",
    }
    out = text
    for old, new in repairs.items():
        out = re.sub(old, new, out, flags=re.IGNORECASE)
    return out


def _title_case_disease(value: str) -> str:
    small_words = {"a", "as", "com", "da", "das", "de", "do", "dos", "e", "em", "na", "no", "por", "para"}
    words = value.lower().split()
    titled: list[str] = []
    for i, word in enumerate(words):
        if i > 0 and word in small_words:
            titled.append(word)
        else:
            titled.append(word.capitalize())
    return " ".join(titled)


def _disease_from_filename(source_stem: str) -> str | None:
    text = source_stem
    text = re.sub(r"\.pdf$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[_\-]+", " ", text)
    text = _apply_filename_repairs(text)
    text = re.sub(r"\b(?:\d{8}|20\d{2}|19\d{2}|v\d+|vers[aã]o|versao|atualizado|final)\b", " ", text, flags=re.IGNORECASE)
    stopwords = (
        "pcdt",
        "protocolo",
        "clinico",
        "clínico",
        "diretrizes",
        "terapeuticas",
        "terapêuticas",
        "ministerio",
        "ministério",
        "saude",
        "saúde",
        "conitec",
        "relatorio",
        "relatório",
    )
    text = re.sub(r"\b(?:" + "|".join(re.escape(w) for w in stopwords) + r")\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -–—:,.")
    if not text:
        return None
    if re.search(r"\banemia\b", text, flags=re.IGNORECASE) and re.search(
        r"\bdeficiencia\b|\bdeficiência\b", text, flags=re.IGNORECASE
    ) and re.search(r"\bferro\b", text, flags=re.IGNORECASE):
        return "Anemia por Deficiência de Ferro"
    return _title_case_disease(text)


def infer_disease_name(
    *,
    source_stem: str,
    source_pdf_rel: str,
    full_text: str,
    first_pages_text: str | None = None,
) -> str | None:
    """Infere a doença/condição clínica por título inicial, com fallback no nome do arquivo."""
    del source_pdf_rel
    title = _disease_from_title_text(first_pages_text or full_text[:12000])
    if title:
        return title
    return _disease_from_filename(source_stem)


def chunk_pages_to_documents(
    pages: list[PageRecord],
    *,
    source_stem: str,
    source_pdf_rel: str,
    headers_to_split_on: list[tuple[str, str]] | None = None,
    chunk_tokens: int = _CHUNK_TOKENS,
    overlap_tokens: int = _OVERLAP_TOKENS,
    chars_per_token: int = _CHARS_PER_TOKEN,
    chunk_strategy: str = _DEFAULT_CHUNK_STRATEGY,
    semantic_breakpoint_percentile: int = _DEFAULT_SEMANTIC_BREAKPOINT_PERCENTILE,
    conitec_catalog: dict[str, dict[str, Any]] | None = None,
) -> list[Document]:
    """
    Produz ``Document`` LangChain por chunk com metadata alinhada ao schema do plano.
    """
    if chunk_strategy not in {"recursive", "semantic"}:
        raise ValueError("chunk_strategy deve ser 'recursive' ou 'semantic'")

    full_text, page_spans = stitch_with_page_spans(pages)
    if not full_text.strip():
        return []
    _log.info(
        "%s: preparando chunking strategy=%s paginas=%s chars=%s",
        source_stem,
        chunk_strategy,
        len(pages),
        len(full_text),
    )

    normalized_text, normalized_to_original = _normalize_pcdt_markdown_headers_with_map(full_text)
    first_pages_text = "\n\n".join(p.markdown for p in pages[:3])
    disease = infer_disease_name(
        source_stem=source_stem,
        source_pdf_rel=source_pdf_rel,
        full_text=full_text,
        first_pages_text=first_pages_text,
    )
    catalog_entry = (
        match_source_to_disease(source_stem, conitec_catalog or {}, candidate_texts=[disease])
        if conitec_catalog
        else None
    )
    disease_meta = metadata_from_catalog_entry(catalog_entry) if catalog_entry else heuristic_metadata(disease)

    headers_to_split_on = headers_to_split_on or _DEFAULT_HEADER_SPLITS
    md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    section_docs = md_splitter.split_text(normalized_text)
    _log.info("%s: %s seções lógicas detectadas", source_stem, len(section_docs))

    chunk_size = chunk_tokens * chars_per_token
    chunk_overlap = overlap_tokens * chars_per_token
    rec = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    semantic_splitter = None
    if chunk_strategy == "semantic":
        _log.info(
            "%s: criando SemanticChunker com embedding Ollama model=%s base_url=%s percentile=%s",
            source_stem,
            _SEMANTIC_EMBEDDING_MODEL,
            _OLLAMA_BASE_URL,
            semantic_breakpoint_percentile,
        )
        semantic_splitter = build_semantic_splitter(
            breakpoint_threshold_amount=semantic_breakpoint_percentile,
        )

    aligned = _align_sections_to_full_text(normalized_text, section_docs)

    chunk_items: list[tuple[str, dict[str, Any], int, int]] = []

    for section_number, (section_doc, g_sec_start, _g_sec_end) in enumerate(aligned, start=1):
        section_name = _section_breadcrumb(section_doc.metadata)
        if chunk_strategy == "semantic":
            _log.info(
                "%s: seção %s/%s semantic start section=%r chars=%s",
                source_stem,
                section_number,
                len(aligned),
                section_name,
                len(section_doc.page_content),
            )
        if chunk_strategy == "semantic":
            triples = _split_section_semantic(
                section_doc,
                global_start=g_sec_start,
                semantic_splitter=semantic_splitter,
                rec=rec,
                chunk_size=chunk_size,
            )
        else:
            triples = _split_section_recursive(
                section_doc,
                global_start=g_sec_start,
                rec=rec,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        if chunk_strategy == "semantic":
            _log.info(
                "%s: seção %s/%s semantic ok chunks=%s",
                source_stem,
                section_number,
                len(aligned),
                len(triples),
            )
        for piece_text, sec_meta, g0, g1 in triples:
            original_g0, original_g1 = _map_normalized_span_to_original(normalized_to_original, g0, g1)
            chunk_items.append((piece_text, sec_meta, original_g0, original_g1))

    chunk_items = _enforce_chunk_item_limits(chunk_items, chunk_size=chunk_size)

    documents: list[Document] = []
    for chunk_index, (piece_text, sec_meta, original_g0, original_g1) in enumerate(chunk_items):
        text_with_overlap = piece_text
        effective_g0 = original_g0
        if chunk_index > 0 and chunk_overlap > 0:
            prev_text, _prev_meta, prev_g0, prev_g1 = chunk_items[chunk_index - 1]
            if _section_breadcrumb(_prev_meta) == _section_breadcrumb(sec_meta):
                overlap_prefix = _tail_for_overlap(prev_text, chunk_overlap)
                if overlap_prefix:
                    effective_g0 = max(prev_g0, prev_g1 - len(overlap_prefix))
                    candidate_with_overlap = (
                        text_with_overlap
                        if text_with_overlap.startswith(overlap_prefix)
                        else _join_semantic_chunks(overlap_prefix, text_with_overlap)
                    )
                    if len(candidate_with_overlap) <= chunk_size:
                        text_with_overlap = candidate_with_overlap

        ps, pe = page_range_for_char_span(page_spans, effective_g0, original_g1)
        h1 = sec_meta.get("header_1")
        h2 = sec_meta.get("header_2")
        meta: dict[str, Any] = {
            "source_stem": source_stem,
            "source_pdf": source_pdf_rel,
            "section": _section_breadcrumb(sec_meta),
            "header_1": h1 if h1 is not None else None,
            "header_2": h2 if h2 is not None else None,
            "page_start": ps,
            "page_end": pe,
            "page_range": [ps, pe],
            "chunk_index": chunk_index,
            "chunk_strategy": chunk_strategy,
            **disease_meta,
        }
        documents.append(Document(page_content=text_with_overlap, metadata=meta))

    _log.info("%s: chunking concluído chunks=%s", source_stem, len(documents))
    return documents


def default_chunks_dir() -> Path:
    return data_root() / DIR_CHUNKS_PCDT


def source_pdf_relative(stem: str) -> str:
    """Caminho ``raw/pcdt/<stem>.pdf`` relativo a ``llm/data``."""
    return (DIR_RAW_PCDT / f"{stem}.pdf").as_posix()


def sidecar_stem(path: Path) -> str:
    """Extrai o stem-base de sidecars ``*.pages.jsonl`` ou ``*.pages.cleaned.jsonl``."""
    name = path.name
    if name.endswith(CLEANED_PAGE_JSONL_SUFFIX):
        return name[: -len(CLEANED_PAGE_JSONL_SUFFIX)]
    if name.endswith(PAGE_JSONL_SUFFIX):
        return name[: -len(PAGE_JSONL_SUFFIX)]
    return path.stem


def write_chunks_jsonl(documents: list[Document], path: Path) -> None:
    """Grava uma linha JSON por chunk: ``text`` + ``metadata``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for doc in documents:
            # Normaliza quebras de linha e espaços em branco para evitar
            # cortes visuais inesperados (ex.: "disponibilidade de\nalimentos").
            # Mantemos o texto legível e adequado para embeddings ao colapsar
            # múltiplos espaços/novas linhas em um único espaço.
            raw_text = doc.page_content or ""
            cleaned_text = re.sub(r"\s+", " ", raw_text).strip()
            row = {
                "text": cleaned_text,
                "metadata": doc.metadata,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_chunks_jsonl_line(line: str) -> Document:
    """Uma linha do formato gravado por ``write_chunks_jsonl`` → ``Document``."""
    row = json.loads(line)
    text = row["text"]
    meta = dict(row["metadata"])
    return Document(page_content=text, metadata=meta)


def assign_stable_chunk_ids(documents: list[Document]) -> None:
    """Define ``doc.id`` como ``{source_stem}:{chunk_index}`` para idempotência no Chroma."""
    for doc in documents:
        stem = doc.metadata.get("source_stem")
        idx = doc.metadata.get("chunk_index")
        if stem is None or idx is None:
            raise ValueError("metadata deve incluir source_stem e chunk_index")
        doc.id = f"{stem}:{idx}"


def read_chunks_jsonl(path: Path) -> list[Document]:
    """Lê ``*.chunks.jsonl``; arquivo vazio ou só linhas em branco → lista vazia."""
    documents: list[Document] = []
    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            documents.append(parse_chunks_jsonl_line(line))
    assign_stable_chunk_ids(documents)
    return documents


def chunk_sidecar_file(
    pages_jsonl: Path,
    *,
    output_path: Path | None = None,
    **kwargs: Any,
) -> tuple[list[Document], Path]:
    """
    Lê ``{stem}.pages.jsonl``, grava ``{stem}.chunks.jsonl`` e devolve documentos + caminho.
    """
    stem = sidecar_stem(pages_jsonl)
    if not pages_jsonl.is_file():
        raise FileNotFoundError(pages_jsonl)

    pages = read_pages_jsonl(pages_jsonl)
    source_pdf_rel = source_pdf_relative(stem)
    docs = chunk_pages_to_documents(
        pages,
        source_stem=stem,
        source_pdf_rel=source_pdf_rel,
        **kwargs,
    )
    out = output_path if output_path is not None else default_chunks_dir() / f"{stem}{CHUNK_JSONL_SUFFIX}"
    write_chunks_jsonl(docs, out)
    return docs, out


def chunk_one_stem(
    stem: str,
    *,
    processed_dir: Path,
    chunks_dir: Path,
    data_base: Path,
    force: bool,
    cleaned_dir: Path | None = None,
    **chunk_kw: Any,
) -> dict[str, Any]:
    """
    Processa um stem: prefere ``cleaned_dir/<stem>.pages.cleaned.jsonl`` quando existir,
    senão lê ``processed_dir/<stem>.pages.jsonl``. Escreve ``chunks_dir/<stem>.chunks.jsonl``.
    Retorna linha de manifesto.
    """
    from pcdt_ingest.manifest import now_iso

    ts = now_iso()
    conitec_catalog_mtime = chunk_kw.pop("conitec_catalog_mtime", None)
    cleaned_base = cleaned_dir or default_cleaned_processed_dir()
    cleaned_pages_path = cleaned_base / f"{stem}{CLEANED_PAGE_JSONL_SUFFIX}"
    raw_pages_path = processed_dir / f"{stem}{PAGE_JSONL_SUFFIX}"
    # pages_path decides which file we will actually read to produce chunks
    pages_path = cleaned_pages_path if cleaned_pages_path.is_file() else raw_pages_path
    out_path = chunks_dir / f"{stem}{CHUNK_JSONL_SUFFIX}"
    # record both the original raw sidecar and the cleaned sidecar (when present)
    rel_pages_raw = raw_pages_path.resolve().relative_to(data_base.resolve()).as_posix()
    cleaned_rel = (
        cleaned_pages_path.resolve().relative_to(data_base.resolve()).as_posix()
        if cleaned_pages_path.is_file()
        else None
    )
    rel_chunks = out_path.resolve().relative_to(data_base.resolve()).as_posix()

    if not pages_path.is_file():
        _log.warning("%s: sidecar inexistente: %s", stem, pages_path)
        return {
            "source_stem": stem,
            # keep pages_jsonl_relative_path pointing to the original (raw) sidecar
            "pages_jsonl_relative_path": rel_pages_raw,
            "cleaned_pages_jsonl_relative_path": cleaned_rel,
            "chunks_jsonl_relative_path": rel_chunks,
            "status": "error",
            "error": "ficheiro .pages.jsonl inexistente",
            "chunk_count": 0,
            "chunk_strategy": str(chunk_kw.get("chunk_strategy", "recursive")),
            "chunked_at": ts,
        }

    if (
        not force
        and out_path.is_file()
        and out_path.stat().st_mtime >= pages_path.stat().st_mtime
        and (
            conitec_catalog_mtime is None
            or out_path.stat().st_mtime >= float(conitec_catalog_mtime)
        )
    ):
        _log.info("%s: chunks atualizados; pulando", stem)
        return {
            "source_stem": stem,
            "pages_jsonl_relative_path": rel_pages_raw,
            "cleaned_pages_jsonl_relative_path": cleaned_rel,
            "chunks_jsonl_relative_path": rel_chunks,
            "status": "skipped",
            "error": None,
            "chunk_count": 0,
            "chunk_strategy": str(chunk_kw.get("chunk_strategy", "recursive")),
            "chunked_at": ts,
        }

    try:
        _log.info(
            "%s: lendo %s strategy=%s",
            stem,
            pages_path,
            chunk_kw.get("chunk_strategy", "recursive"),
        )
        docs, written = chunk_sidecar_file(
            pages_path,
            output_path=out_path,
            **chunk_kw,
        )
        _log.info("%s: gravado %s chunks=%s", stem, written, len(docs))
    except Exception as e:
        _log.exception("Falha ao fragmentar %s", stem)
        return {
            "source_stem": stem,
            "pages_jsonl_relative_path": rel_pages_raw,
            "cleaned_pages_jsonl_relative_path": cleaned_rel,
            "chunks_jsonl_relative_path": rel_chunks,
            "status": "error",
            "error": str(e),
            "chunk_count": 0,
            "chunk_strategy": str(chunk_kw.get("chunk_strategy", "recursive")),
            "chunked_at": ts,
        }

    return {
        "source_stem": stem,
        "pages_jsonl_relative_path": rel_pages_raw,
        "cleaned_pages_jsonl_relative_path": cleaned_rel,
        "chunks_jsonl_relative_path": rel_chunks,
        "status": "ok",
        "error": None,
        "chunk_count": len(docs),
        "chunk_strategy": str(chunk_kw.get("chunk_strategy", "recursive")),
        "chunked_at": ts,
    }
