"""Clinical query understanding for the medical chat RAG flow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from math import sqrt
import re
from typing import Any, Iterable

try:
    from pcdt_ingest.clinical.catalog_resolver import CatalogConceptResolver
    from pcdt_ingest.reference_data.conitec_catalog import normalize_text_for_match
except Exception:  # pragma: no cover
    CatalogConceptResolver = None  # type: ignore[assignment]

    def normalize_text_for_match(value: Any) -> str:  # type: ignore[no-redef]
        text = re.sub(r"[^a-zA-Z0-9À-ÿ]+", " ", str(value or "").lower())
        return re.sub(r"\s+", " ", text).strip()


CID10_RE = re.compile(r"\b[A-Z]\d{2}(?:\.\d{1,2})?\b", re.IGNORECASE)

INTENT_DESCRIPTIONS = {
    "criterios_inclusao": "pergunta sobre quem pode ser incluído no protocolo, critérios de elegibilidade ou critérios de inclusão",
    "criterios_exclusao": "pergunta sobre quem deve ser excluído do protocolo, critérios de exclusão ou contraindicações de inclusão",
    "diagnostico": "pergunta sobre diagnóstico, reconhecer uma condição clínica, reconhecimento clínico, sinais, sintomas, suspeita clínica ou confirmação diagnóstica",
    "tratamento": "pergunta sobre conduta terapêutica, tratamento, manejo, intervenção ou como tratar uma condição",
    "monitoramento": "pergunta sobre acompanhamento, exames de controle, seguimento, monitorização ou como monitorar",
    "medicamento": "pergunta sobre medicamento, fármaco, dose, posologia, esquema medicamentoso ou apresentação",
    "regulatorio": "pergunta sobre portaria, regulação, financiamento, componente especializado ou regras administrativas",
    "geral": "pergunta geral sobre uma diretriz clínica sem solicitar uma seção específica",
}

INTENT_SECTION_LABELS = {
    "criterios_inclusao": "CRITÉRIOS DE INCLUSÃO",
    "criterios_exclusao": "CRITÉRIOS DE EXCLUSÃO",
    "diagnostico": "DIAGNÓSTICO",
    "tratamento": "TRATAMENTO",
    "monitoramento": "MONITORAMENTO",
    "medicamento": "FÁRMACOS",
    "regulatorio": "REGULAÇÃO",
}


@dataclass(frozen=True)
class IntentResult:
    intent: str
    confidence: float
    method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ClinicalIntentClassifier:
    """Classify clinical intent using semantic similarity to canonical descriptions."""

    def classify(self, query: str) -> dict[str, Any]:
        query_norm = normalize_text_for_match(query)
        if not query_norm:
            return IntentResult("geral", 0.0, "embedding").to_dict()
        query_embedding = _char_ngram_embedding(query_norm)
        scored = []
        for intent, description in INTENT_DESCRIPTIONS.items():
            score = _cosine_similarity(query_embedding, _char_ngram_embedding(description))
            scored.append((intent, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        intent, score = scored[0]
        if score < 0.18:
            intent = "geral"
        return IntentResult(intent, round(float(score), 4), "embedding").to_dict()


def classify_clinical_intent(query: str) -> dict[str, Any]:
    return ClinicalIntentClassifier().classify(query)


def extract_explicit_cid10_codes(query: str) -> list[str]:
    return _dedupe(code.upper() for code in CID10_RE.findall(query or ""))


def resolve_catalog_candidates(
    query: str,
    catalog: Any,
    linked_entities: list[dict[str, Any]] | None = None,
    intent: dict[str, Any] | None = None,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if not catalog or CatalogConceptResolver is None:
        return []
    resolver = CatalogConceptResolver(catalog)
    candidates = resolver.resolve(query, linked_entities or [], intent, limit=limit)
    if isinstance(candidates, dict):
        return []
    return [candidate.to_dict(include_entry=True) for candidate in candidates]


def understand_clinical_query(query: str, conitec_catalog: Any | None = None) -> dict[str, Any]:
    original = str(query or "").strip()
    intent = classify_clinical_intent(original)
    cid_codes = extract_explicit_cid10_codes(original)
    candidates = resolve_catalog_candidates(original, conitec_catalog, [], intent) if conitec_catalog else []
    detected = _detected_disease_from_candidates(candidates)
    return {
        "original_query": original,
        "normalized_query": normalize_text_for_match(original),
        "intent": intent["intent"],
        "intent_result": intent,
        "catalog_candidates": [_public_candidate(c) for c in candidates],
        "detected_disease": detected,
        "detected_cid10_codes": cid_codes,
        "detected_sections": [INTENT_SECTION_LABELS[intent["intent"]]] if intent["intent"] in INTENT_SECTION_LABELS else [],
    }


def _detected_disease_from_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    first = candidates[0]
    if float(first.get("score") or 0.0) < 0.84:
        return None
    return {
        "name": first.get("disease"),
        "normalized": normalize_text_for_match(first.get("disease") or first.get("diretriz") or ""),
        "confidence": first.get("score"),
        "match_type": ",".join(first.get("reasons") or []),
        "catalog_candidate": _public_candidate(first),
    }


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "diretriz": candidate.get("diretriz"),
        "disease": candidate.get("disease"),
        "score": candidate.get("score"),
        "matched_fields": candidate.get("matched_fields") or [],
        "reasons": candidate.get("reasons") or [],
        "source": candidate.get("source") or "catalog_semantic",
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
        key = normalize_text_for_match(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if limit is not None and len(out) >= limit:
            break
    return out


def _char_ngram_embedding(text: str, n: int = 3) -> dict[str, float]:
    padded = f" {normalize_text_for_match(text)} "
    if len(padded) < n:
        return {padded: 1.0} if padded.strip() else {}
    vector: dict[str, float] = {}
    for idx in range(len(padded) - n + 1):
        key = padded[idx : idx + n]
        vector[key] = vector.get(key, 0.0) + 1.0
    return vector


def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0.0) for key, value in left.items())
    left_norm = sqrt(sum(value * value for value in left.values()))
    right_norm = sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
