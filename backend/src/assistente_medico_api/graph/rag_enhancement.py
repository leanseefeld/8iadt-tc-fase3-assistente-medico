"""Helpers puros para expansão, reranking, contexto e auditoria RAG."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from langchain_core.documents import Document

try:
    from pcdt_ingest.paths import data_root
    from pcdt_ingest.reference_data.conitec_catalog import (
        DEFAULT_CATALOG_RELATIVE_PATH,
        normalize_text_for_match,
        read_catalog_jsonl,
    )
except Exception:  # pragma: no cover - backend pode ser importado sem pacote llm instalado.
    data_root = None  # type: ignore[assignment]
    DEFAULT_CATALOG_RELATIVE_PATH = Path("processed/conitec/pcdt_catalog.jsonl")

    def normalize_text_for_match(value: Any) -> str:  # type: ignore[no-redef]
        return re.sub(r"\s+", " ", str(value or "").lower()).strip()

    def read_catalog_jsonl(_path: Path) -> dict[str, dict[str, Any]]:  # type: ignore[no-redef]
        return {}


CID10_RE = re.compile(r"\b[A-Z]\d{2}(?:\.\d{1,2})?\b", re.IGNORECASE)

SECTION_INTENT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("criterios_inclusao", ("criterios de inclusao", "criterio de inclusao", "inclusao", "incluido", "incluidos")),
    ("criterios_exclusao", ("criterios de exclusao", "criterio de exclusao", "exclusao", "excluido", "excluidos")),
    ("monitoramento", ("monitoramento", "monitorizacao", "acompanhamento", "seguimento")),
    ("diagnostico", ("diagnostico", "diagnosticar", "confirmacao diagnostica")),
    ("tratamento", ("tratamento", "terapia", "conduta", "manejo")),
    ("dose", ("dose", "posologia", "dosagem", "esquema terapeutico")),
    ("medicamento", ("medicamento", "farmaco", "remedio")),
    ("regulacao", ("regulacao", "controle", "avaliacao pelo gestor", "gestor")),
    ("exames", ("exame", "exames", "laboratorial", "laboratoriais")),
]

ADMIN_SECTION_TERMS = (
    "regulacao",
    "controle",
    "avaliacao pelo gestor",
    "referencias",
    "metodologia",
    "busca e avaliacao da literatura",
)

_GENERIC_TERM_TOKENS = {
    "a",
    "as",
    "com",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "no",
    "na",
    "para",
    "por",
}

SECTION_BOOST_TERMS = {
    "criterios_inclusao": ("criterios de inclusao",),
    "criterios_exclusao": ("criterios de exclusao",),
    "tratamento": ("tratamento", "tratamento medicamentoso"),
    "diagnostico": ("diagnostico",),
    "monitoramento": ("monitoramento", "monitorizacao", "acompanhamento"),
    "dose": ("tratamento", "posologia", "dose"),
    "medicamento": ("tratamento", "medicamento", "medicamentos"),
    "regulacao": ("regulacao", "controle", "avaliacao pelo gestor"),
    "exames": ("diagnostico", "exames", "laboratorial"),
}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                decoded = json.loads(text)
                if isinstance(decoded, list):
                    return [str(item).strip() for item in decoded if str(item).strip()]
            except Exception:
                return [text]
        return [text]
    return [str(value).strip()] if str(value).strip() else []


def _dedupe(values: Iterable[Any], *, limit: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = normalize_text_for_match(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if limit is not None and len(out) >= limit:
            break
    return out


def load_local_conitec_catalog(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Carrega o catálogo local processado; nunca baixa a planilha em runtime."""
    if path is None:
        if data_root is None:
            return {}
        path = data_root() / DEFAULT_CATALOG_RELATIVE_PATH
    if not path.is_file():
        return {}
    return read_catalog_jsonl(path)


def _catalog_entries(catalog: Any) -> list[dict[str, Any]]:
    if not catalog:
        return []
    if isinstance(catalog, dict):
        return [entry for entry in catalog.values() if isinstance(entry, dict)]
    if isinstance(catalog, list):
        return [entry for entry in catalog if isinstance(entry, dict)]
    return []


def _haystack_for_entry(entry: dict[str, Any]) -> str:
    parts = [
        entry.get("diretriz", ""),
        entry.get("disease", ""),
        entry.get("disease_normalized", ""),
        entry.get("diretriz_normalized", ""),
        *_as_list(entry.get("cid10_codes")),
        *_as_list(entry.get("cid10_descriptions")),
        *_as_list(entry.get("medicamentos")),
        *_as_list(entry.get("descricao_siglas")),
    ]
    return " ".join(normalize_text_for_match(part) for part in parts if part)


def _match_entry(query_norm: str, query_tokens: set[str], cid_codes: list[str], entry: dict[str, Any]) -> bool:
    cid_values = {code.upper() for code in _as_list(entry.get("cid10_codes"))}
    if cid_codes and any(code.upper() in cid_values for code in cid_codes):
        return True

    disease_norm = normalize_text_for_match(entry.get("disease") or entry.get("diretriz") or "")
    if disease_norm and (disease_norm in query_norm or query_norm in disease_norm):
        return True

    haystack = _haystack_for_entry(entry)
    if query_norm and query_norm in haystack:
        return True
    hay_tokens = set(haystack.split())
    relevant_tokens = {tok for tok in query_tokens if len(tok) >= 3}
    acronym_tokens = {tok for tok in query_tokens if 2 <= len(tok) <= 5}
    if acronym_tokens & hay_tokens:
        return True
    return bool(relevant_tokens and len(relevant_tokens & hay_tokens) >= min(2, len(relevant_tokens)))


def _detect_section_intent(query_norm: str) -> str | None:
    for intent, patterns in SECTION_INTENT_PATTERNS:
        if any(pattern in query_norm for pattern in patterns):
            return intent
    return None


def extract_query_entities(query: str, catalog: Any | None = None) -> dict[str, Any]:
    """Extrai entidades simples da pergunta sem depender de LLM."""
    query_norm = normalize_text_for_match(query)
    cid10_codes = _dedupe(code.upper() for code in CID10_RE.findall(query or ""))
    disease_terms: list[str] = []
    medication_terms: list[str] = []

    for entry in _catalog_entries(catalog):
        disease = str(entry.get("disease") or entry.get("diretriz") or "").strip()
        disease_norm = normalize_text_for_match(disease)
        if disease and disease_norm and (disease_norm in query_norm or query_norm in disease_norm):
            disease_terms.append(disease)
        for med in _as_list(entry.get("medicamentos")):
            med_norm = normalize_text_for_match(med)
            med_tokens = [tok for tok in med_norm.split() if len(tok) >= 4 and tok not in _GENERIC_TERM_TOKENS]
            if med_norm and (
                med_norm in query_norm
                or any(tok in query_norm.split() for tok in med_tokens[:3])
            ):
                medication_terms.append(med)

    return {
        "cid10_codes": cid10_codes,
        "disease_terms": _dedupe(disease_terms),
        "medication_terms": _dedupe(medication_terms),
        "section_intent": _detect_section_intent(query_norm),
    }


def expand_query_with_conitec_catalog(query: str, catalog: Any, max_terms: int = 20) -> dict[str, Any]:
    """Expande a query com diretriz, CID-10, medicamentos e descrições do catálogo local."""
    original = (query or "").strip()
    if not original or not catalog:
        return {
            "original_query": original,
            "expanded_query": original,
            "matched_diseases": [],
            "matched_cid10_codes": [],
            "matched_medications": [],
            "matched_terms": [],
            "entities": extract_query_entities(original, catalog),
        }

    query_norm = normalize_text_for_match(original)
    query_tokens = set(query_norm.split())
    entities = extract_query_entities(original, catalog)
    matched_entries = [
        entry
        for entry in _catalog_entries(catalog)
        if _match_entry(query_norm, query_tokens, entities["cid10_codes"], entry)
    ]

    matched_diseases = _dedupe(entry.get("disease") or entry.get("diretriz") for entry in matched_entries)
    matched_cids = _dedupe(code for entry in matched_entries for code in _as_list(entry.get("cid10_codes")))
    matched_meds = _dedupe(med for entry in matched_entries for med in _as_list(entry.get("medicamentos")))
    descriptions = _dedupe(desc for entry in matched_entries for desc in _as_list(entry.get("cid10_descriptions")))
    siglas = _dedupe(term for entry in matched_entries for term in _as_list(entry.get("descricao_siglas")))

    additions = _dedupe(
        [
            *matched_diseases,
            *matched_cids,
            *descriptions,
            *matched_meds,
            *siglas,
        ],
        limit=max_terms,
    )
    expanded_query = " ".join(_dedupe([original, *additions]))
    return {
        "original_query": original,
        "expanded_query": expanded_query or original,
        "matched_diseases": matched_diseases,
        "matched_cid10_codes": matched_cids,
        "matched_medications": matched_meds,
        "matched_terms": additions,
        "entities": entities,
    }


def _metadata_text(metadata: dict[str, Any]) -> str:
    parts = []
    for key in (
        "source_stem",
        "section",
        "header_1",
        "header_2",
        "disease",
        "disease_normalized",
        "diretriz",
        "cid10_codes",
        "cid10_descriptions",
        "medicamentos",
        "portarias",
    ):
        value = metadata.get(key)
        parts.extend(_as_list(value))
    return normalize_text_for_match(" ".join(parts))


def _doc_from_pair(item: Any) -> tuple[Document, float | None]:
    if isinstance(item, tuple) and item:
        doc = item[0]
        score = item[1] if len(item) > 1 else None
        return doc, float(score) if score is not None else None
    return item, None


def rerank_documents(
    query: str,
    expanded_query: dict[str, Any],
    documents: list[Any],
    final_k: int = 6,
) -> list[Document]:
    """Rerank heurístico explicável sobre candidatos vindos do Chroma."""
    if final_k < 1:
        return []

    entities = expanded_query.get("entities") or extract_query_entities(query)
    query_norm = normalize_text_for_match(query)
    cids = {code.upper() for code in (entities.get("cid10_codes") or expanded_query.get("matched_cid10_codes") or [])}
    disease_terms = [normalize_text_for_match(t) for t in (entities.get("disease_terms") or expanded_query.get("matched_diseases") or [])]
    medication_terms = [
        normalize_text_for_match(t)
        for t in (entities.get("medication_terms") or expanded_query.get("matched_medications") or [])
    ]
    exact_terms = [
        normalize_text_for_match(term)
        for term in expanded_query.get("matched_terms", [])
        if len(normalize_text_for_match(term)) >= 3
    ][:20]
    intent = entities.get("section_intent")

    total = max(1, len(documents))
    ranked: list[tuple[float, Document]] = []
    for idx, item in enumerate(documents):
        doc, dense_score = _doc_from_pair(item)
        metadata = dict(getattr(doc, "metadata", {}) or {})
        text = str(getattr(doc, "page_content", "") or "")
        text_norm = normalize_text_for_match(text)
        meta_norm = _metadata_text(metadata)
        section_norm = normalize_text_for_match(
            " ".join(_as_list(metadata.get("section")) + _as_list(metadata.get("header_1")) + _as_list(metadata.get("header_2")))
        )
        source_norm = normalize_text_for_match(metadata.get("source_stem") or "")

        base = 1.0 - (idx / total)
        boost = 0.0
        penalty = 0.0
        reasons: list[str] = []

        meta_cids = {code.upper() for code in _as_list(metadata.get("cid10_codes"))}
        for cid in sorted(cids):
            if cid in meta_cids:
                boost += 0.45
                reasons.append(f"cid10_match:{cid}")
            if cid and cid.lower() in text.lower():
                boost += 0.12
                reasons.append(f"cid10_text:{cid}")

        for disease in disease_terms:
            if disease and disease in meta_norm:
                boost += 0.25
                reasons.append(f"disease_match:{disease}")
            elif disease and disease in source_norm:
                boost += 0.08
                reasons.append(f"source_disease_hint:{disease}")

        for med in medication_terms:
            if med and med in meta_norm:
                boost += 0.35
                reasons.append(f"medication_match:{med}")
            if med and med in text_norm:
                boost += 0.12
                reasons.append(f"medication_text:{med}")

        if intent:
            for section_term in SECTION_BOOST_TERMS.get(str(intent), ()):
                if section_term in section_norm:
                    boost += 0.50
                    reasons.append(f"section_match:{intent}")
                    break

        exact_hits = 0
        for term in exact_terms:
            if term and (term in text_norm or term in meta_norm):
                exact_hits += 1
        if exact_hits:
            term_boost = min(0.25, exact_hits * 0.035)
            boost += term_boost
            reasons.append(f"exact_terms:{exact_hits}")

        is_admin = any(term in section_norm for term in ADMIN_SECTION_TERMS)
        if is_admin and intent not in {"regulacao"}:
            penalty += 0.25
            reasons.append("penalty:administrative_section")

        final_score = base + boost - penalty
        metadata.update(
            {
                "dense_score": dense_score,
                "dense_rank": idx + 1,
                "dense_rank_score": round(base, 6),
                "heuristic_score": round(boost - penalty, 6),
                "final_score": round(final_score, 6),
                "ranking_reasons": reasons,
            }
        )
        ranked_doc = Document(page_content=text, metadata=metadata, id=getattr(doc, "id", None))
        ranked.append((final_score, ranked_doc))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [doc for _score, doc in ranked[:final_k]]


def _format_list(value: Any, *, max_items: int = 10, max_chars: int = 500) -> str:
    items = _as_list(value)
    if not items:
        return "-"
    shown = items[:max_items]
    text = "; ".join(shown)
    if len(items) > max_items:
        text += "; ..."
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def format_context_document(doc: Document, rank: int) -> str:
    """Formata um documento recuperado com metadados ricos para o prompt."""
    meta = dict(doc.metadata or {})
    page_start = meta.get("page_start", "?")
    page_end = meta.get("page_end", "?")
    reasons = _format_list(meta.get("ranking_reasons"), max_items=8, max_chars=240)
    return (
        f"[Documento {rank}]\n"
        f"Diretriz: {meta.get('diretriz') or '-'}\n"
        f"Doença: {meta.get('disease') or '-'}\n"
        f"CID-10: {_format_list(meta.get('cid10_codes'), max_items=12, max_chars=240)}\n"
        f"Medicamentos relacionados: {_format_list(meta.get('medicamentos'), max_items=10, max_chars=600)}\n"
        f"Seção: {meta.get('section') or meta.get('header_1') or '-'}\n"
        f"Portaria: {_format_list(meta.get('portarias'), max_items=4, max_chars=240)}\n"
        f"Data da Portaria: {_format_list(meta.get('datas_portaria'), max_items=4, max_chars=120)}\n"
        f"Fonte: {meta.get('source_pdf') or meta.get('source_stem') or '-'}\n"
        f"Páginas: {page_start}-{page_end}\n"
        f"Score final: {meta.get('final_score', '-')}\n"
        f"Motivos do ranking: {reasons}\n\n"
        f"Trecho:\n{str(doc.page_content or '').strip()}"
    )


def format_rich_context_block(docs: list[Document]) -> str:
    return "\n\n---\n\n".join(format_context_document(doc, i) for i, doc in enumerate(docs, start=1))


def document_audit_record(doc: Document, rank: int) -> dict[str, Any]:
    meta = dict(doc.metadata or {})
    return {
        "rank": rank,
        "source_stem": meta.get("source_stem"),
        "source_pdf": meta.get("source_pdf"),
        "diretriz": meta.get("diretriz"),
        "disease": meta.get("disease"),
        "section": meta.get("section"),
        "page_start": meta.get("page_start"),
        "page_end": meta.get("page_end"),
        "page_range": _as_list(meta.get("page_range")) or meta.get("page_range"),
        "cid10_codes": _as_list(meta.get("cid10_codes")),
        "medicamentos": _as_list(meta.get("medicamentos")),
        "portarias": _as_list(meta.get("portarias")),
        "dense_score": meta.get("dense_score"),
        "heuristic_score": meta.get("heuristic_score"),
        "final_score": meta.get("final_score"),
        "ranking_reasons": _as_list(meta.get("ranking_reasons")),
    }


def build_audit_payload(
    *,
    question: str,
    expansion: dict[str, Any],
    documents: list[Document],
    retrieval_candidates_k: int,
    retrieval_final_k: int,
    answer: str = "",
    audit_id: str | None = None,
) -> dict[str, Any]:
    return {
        "audit_id": audit_id or str(uuid.uuid4()),
        "question": question,
        "original_query": expansion.get("original_query") or question,
        "expanded_query": expansion.get("expanded_query") or question,
        "matched_diseases": expansion.get("matched_diseases") or [],
        "matched_cid10_codes": expansion.get("matched_cid10_codes") or [],
        "matched_medications": expansion.get("matched_medications") or [],
        "matched_terms": expansion.get("matched_terms") or [],
        "retrieval_candidates_k": retrieval_candidates_k,
        "retrieval_final_k": retrieval_final_k,
        "documents": [document_audit_record(doc, i) for i, doc in enumerate(documents, start=1)],
        "answer": answer,
        "created_at": datetime.now(UTC).isoformat(),
    }


def append_audit_jsonl(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
