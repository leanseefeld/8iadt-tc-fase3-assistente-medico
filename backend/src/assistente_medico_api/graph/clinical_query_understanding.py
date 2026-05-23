"""Clinical query understanding for the medical chat RAG flow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import json
import logging
from math import sqrt
import re
from typing import Any, Iterable

try:
    from pcdt_ingest.clinical.catalog_resolver import CatalogConceptResolver
    from pcdt_ingest.clinical.entity_resolver import BiomedicalEntityResolver
    from pcdt_ingest.reference_data.conitec_catalog import normalize_text_for_match
except Exception:  # pragma: no cover
    CatalogConceptResolver = None  # type: ignore[assignment]
    BiomedicalEntityResolver = None  # type: ignore[assignment]

    def normalize_text_for_match(value: Any) -> str:  # type: ignore[no-redef]
        text = re.sub(r"[^a-zA-Z0-9À-ÿ]+", " ", str(value or "").lower())
        return re.sub(r"\s+", " ", text).strip()


_logger = logging.getLogger("assistente_medico.rag")

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


class QueryExpansionFromCatalog:
    """Build a conservative query expansion using only catalog candidates."""

    def expand(
        self,
        original_query: str,
        intent: dict[str, Any],
        linked_entities: list[dict[str, Any]],
        catalog_candidates: list[dict[str, Any]],
        *,
        max_terms: int = 10,
    ) -> dict[str, Any]:
        added: list[str] = []
        candidates = [c for c in catalog_candidates if float(c.get("score") or 0.0) >= 0.84]
        if candidates:
            first = candidates[0]
            added.append(str(first.get("diretriz") or first.get("disease") or ""))
        label = INTENT_SECTION_LABELS.get(str(intent.get("intent") or ""))
        if candidates and label:
            added.append(label)
        added_terms = _dedupe(added, limit=max_terms)
        expanded_query = f"{original_query} {' '.join(added_terms)}".strip() if added_terms else original_query
        confidence = min([float(c.get("score") or 0.0) for c in candidates] or [0.0])
        if added_terms and not candidates:
            confidence = float(intent.get("confidence") or 0.0)
        return {
            "original_query": original_query,
            "expanded_query": expanded_query,
            "added_terms": added_terms,
            "source": "catalog_candidates",
            "confidence": round(confidence, 4),
        }


@lru_cache(maxsize=1)
def _entity_resolver() -> Any | None:
    if BiomedicalEntityResolver is None:
        return None
    try:
        return BiomedicalEntityResolver()
    except Exception as exc:
        _logger.debug("biomedical_entity_resolver_init_failed; erro=%s", exc)
        return None


def classify_clinical_intent(query: str) -> dict[str, Any]:
    return ClinicalIntentClassifier().classify(query)


def detect_clinical_intent(query: str) -> str | None:
    return classify_clinical_intent(query).get("intent")


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
    linked_entities = _extract_linked_entities(original)
    candidates = resolve_catalog_candidates(original, conitec_catalog, linked_entities, intent) if conitec_catalog else []
    detected = _detected_disease_from_candidates(candidates)
    return {
        "original_query": original,
        "normalized_query": normalize_text_for_match(original),
        "intent": intent["intent"],
        "intent_result": intent,
        "linked_entities": linked_entities,
        "catalog_candidates": [_public_candidate(c) for c in candidates],
        "detected_disease": detected,
        "detected_cid10_codes": cid_codes,
        "detected_medications": [],
        "detected_sections": [INTENT_SECTION_LABELS[intent["intent"]]] if intent["intent"] in INTENT_SECTION_LABELS else [],
        "clinical_terms": [e.get("text") for e in linked_entities if e.get("text")],
        "negated_terms": [],
        "uncertain_terms": [],
    }


def expand_query_for_medical_chat(
    understanding: dict[str, Any],
    catalog: Any | None = None,
    max_terms: int = 10,
) -> dict[str, Any]:
    expansion = QueryExpansionFromCatalog().expand(
        str(understanding.get("original_query") or ""),
        understanding.get("intent_result") or {"intent": understanding.get("intent"), "confidence": 0.0},
        understanding.get("linked_entities") or [],
        understanding.get("catalog_candidates") or [],
        max_terms=max_terms,
    )
    return {
        **expansion,
        "expansion_reason": ["catalog_candidate" if expansion["added_terms"] else "low_confidence_no_filter"],
    }


def match_disease_from_catalog(query: str, catalog: Any, min_score: int = 84) -> dict[str, Any] | None:
    candidates = resolve_catalog_candidates(query, catalog, [], None, limit=2)
    if not candidates or float(candidates[0].get("score") or 0.0) < (min_score / 100.0):
        return None
    if len(candidates) > 1 and abs(float(candidates[0]["score"]) - float(candidates[1]["score"])) < 0.04:
        return None
    first = candidates[0]
    return {
        "name": first.get("disease"),
        "normalized": normalize_text_for_match(first.get("disease") or first.get("diretriz") or ""),
        "confidence": first.get("score"),
        "match_type": ",".join(first.get("reasons") or []),
        "catalog_candidate": _public_candidate(first),
        "catalog_entry": first.get("entry"),
    }


def _extract_linked_entities(query: str) -> list[dict[str, Any]]:
    resolver = _entity_resolver()
    if resolver is None:
        return []
    try:
        entities = resolver.extract_and_link(query)
    except Exception as exc:
        _logger.debug("biomedical_entity_resolver_failed; erro=%s", exc)
        return []
    return [entity.to_dict() if hasattr(entity, "to_dict") else dict(entity) for entity in entities]


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


class CatalogCandidateRetriever:
    """Compatibility facade over CatalogConceptResolver."""

    def __init__(self, catalog: Any, *, min_score: int = 84, ambiguity_margin: int = 4) -> None:
        self.catalog = catalog
        self.min_score = min_score / 100.0
        self.ambiguity_margin = ambiguity_margin / 100.0

    def search(self, query: str, *, limit: int = 5) -> list[Any]:
        candidates = resolve_catalog_candidates(query, self.catalog, [], None, limit=limit)
        return [_CandidateView(c) for c in candidates if float(c.get("score") or 0.0) >= self.min_score]

    def best_unambiguous(self, query: str) -> Any | None:
        candidates = self.search(query, limit=2)
        if not candidates:
            return None
        if len(candidates) > 1 and candidates[0].score - candidates[1].score < self.ambiguity_margin:
            return None
        return candidates[0]


class _CandidateView:
    def __init__(self, data: dict[str, Any]) -> None:
        self.diretriz = str(data.get("diretriz") or "")
        self.disease = str(data.get("disease") or "")
        self.disease_normalized = normalize_text_for_match(self.disease or self.diretriz)
        self.score = float(data.get("score") or 0.0) * 100.0
        self.reasons = tuple(data.get("reasons") or [])
        self.matched_fields = tuple(data.get("matched_fields") or [])
        self.entry = data.get("entry") or {}

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "diretriz": self.diretriz,
            "disease": self.disease,
            "disease_normalized": self.disease_normalized,
            "score": round(self.score, 4),
            "reasons": list(self.reasons),
            "matched_fields": list(self.matched_fields),
        }
