"""Entendimento clínico do chat médico baseado no catálogo Conitec."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import logging
from math import sqrt
import re
from typing import Any, Iterable

try:
    from pcdt_ingest.reference_data.conitec_catalog import normalize_text_for_match
except Exception:  # pragma: no cover

    def normalize_text_for_match(value: Any) -> str:  # type: ignore[no-redef]
        text = re.sub(r"[^a-zA-Z0-9À-ÿ]+", " ", str(value or "").lower())
        return re.sub(r"\s+", " ", text).strip()

# Optional clinical resolver (scispaCy / spaCy wrapper) and catalog resolver.
try:
    from pcdt_ingest.clinical.entity_resolver import ClinicalEntityResolver  # type: ignore
    from pcdt_ingest.clinical.catalog_resolver import CatalogConceptResolver  # type: ignore
except Exception:  # pragma: no cover
    ClinicalEntityResolver = None  # type: ignore
    CatalogConceptResolver = None  # type: ignore


_logger = logging.getLogger("assistente_medico.rag")

CID10_RE = re.compile(r"\b[A-Z]\d{2}(?:\.\d{1,2})?\b", re.IGNORECASE)

INTENT_DESCRIPTIONS = {
    "criterios_inclusao": (
        "pergunta sobre quem pode ser incluído no protocolo ou critérios de elegibilidade",
        "pergunta quais são os critérios de inclusão para uma doença ou diretriz",
    ),
    "criterios_exclusao": (
        "pergunta sobre quem deve ser excluído ou contraindicações de inclusão",
        "pergunta quais são os critérios de exclusão para uma doença ou diretriz",
    ),
    "diagnostico": (
        "pergunta sobre diagnóstico, confirmação diagnóstica ou classificação",
        "pergunta como confirmar o diagnóstico segundo a diretriz",
    ),
    "tratamento": (
        "pergunta sobre tratamento, manejo terapêutico ou conduta",
        "pergunta como tratar uma doença segundo o protocolo",
    ),
    "monitoramento": (
        "pergunta sobre acompanhamento, exames de controle ou seguimento",
        "pergunta como monitorar ou acompanhar um paciente",
    ),
    "medicamento": (
        "pergunta sobre medicamento, dose, posologia ou fármaco",
        "pergunta sobre dose ou posologia de medicamento",
    ),
    "cid10": (
        "pergunta sobre código CID-10 ou classificação internacional de doenças",
        "pergunta o que o protocolo diz sobre um código CID",
    ),
    "regulatorio": (
        "pergunta sobre portaria, financiamento, regulação ou gestor",
        "pergunta sobre regras administrativas do componente especializado",
    ),
}

INTENT_SECTION_LABELS = {
    "criterios_inclusao": ["CRITÉRIOS DE INCLUSÃO"],
    "criterios_exclusao": ["CRITÉRIOS DE EXCLUSÃO"],
    "diagnostico": ["DIAGNÓSTICO"],
    "tratamento": ["TRATAMENTO"],
    "monitoramento": ["MONITORAMENTO", "ACOMPANHAMENTO"],
    "medicamento": ["FÁRMACOS", "TRATAMENTO MEDICAMENTOSO", "POSOLOGIA"],
    "cid10": ["CID-10"],
    "regulatorio": ["REGULAÇÃO", "CONTROLE", "AVALIAÇÃO PELO GESTOR"],
}

TREATMENT_INTENTS = {"tratamento", "medicamento"}
SECTION_ONLY_INTENTS = {"criterios_inclusao", "criterios_exclusao"}


@dataclass(frozen=True)
class CatalogCandidate:
    diretriz: str
    disease: str
    disease_normalized: str
    score: float
    reasons: tuple[str, ...]
    matched_fields: tuple[str, ...]
    entry: dict[str, Any]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "diretriz": self.diretriz,
            "disease": self.disease,
            "disease_normalized": self.disease_normalized,
            "score": round(min(100.0, self.score), 4),
            "reasons": list(self.reasons),
            "matched_fields": list(self.matched_fields),
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


def _catalog_entries(catalog: Any) -> list[dict[str, Any]]:
    if not catalog:
        return []
    if isinstance(catalog, dict):
        return [entry for entry in catalog.values() if isinstance(entry, dict)]
    if isinstance(catalog, list):
        return [entry for entry in catalog if isinstance(entry, dict)]
    return []


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


def _safe_ratio(a: str, b: str) -> int:
    try:
        from rapidfuzz import fuzz

        return int(max(fuzz.WRatio(a, b), fuzz.token_sort_ratio(a, b), fuzz.token_set_ratio(a, b)))
    except Exception:
        from difflib import SequenceMatcher

        return int(SequenceMatcher(None, a, b).ratio() * 100)


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


def _contains_complete_field(query_norm: str, field_norm: str) -> bool:
    if not query_norm or not field_norm:
        return False
    return f" {field_norm} " in f" {query_norm} " or query_norm == field_norm


def _substring_relevance(query_norm: str, field_norm: str) -> float:
    if not query_norm or not field_norm:
        return 0.0
    if query_norm == field_norm:
        return 1.0
    if query_norm in field_norm:
        return len(query_norm) / max(1, len(field_norm))
    if field_norm in query_norm:
        return len(field_norm) / max(1, len(query_norm))
    return 0.0


def _entry_fields(entry: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "diretriz": _as_list(entry.get("diretriz")),
        "disease": _as_list(entry.get("disease")),
        "disease_normalized": _as_list(entry.get("disease_normalized")),
        "cid10_codes": _as_list(entry.get("cid10_codes")),
        "cid10_descriptions": _as_list(entry.get("cid10_descriptions")),
        "medicamentos": _as_list(entry.get("medicamentos")),
        "descricao_siglas": _as_list(entry.get("descricao_siglas")),
        "source_stem": _as_list(entry.get("source_stem")),
    }


class CatalogCandidateRetriever:
    """Busca candidatos no catálogo Conitec usando campos completos."""

    def __init__(self, catalog: Any, *, min_score: int = 90, ambiguity_margin: int = 5) -> None:
        self.catalog = catalog
        self.min_score = min_score
        self.ambiguity_margin = ambiguity_margin

    def search(self, query: str, *, limit: int = 5) -> list[CatalogCandidate]:
        query_norm = normalize_text_for_match(query)
        cid_codes = set(extract_explicit_cid10_codes(query))
        candidates: list[CatalogCandidate] = []
        for entry in _catalog_entries(self.catalog):
            candidate = self._score_entry(query_norm, cid_codes, entry)
            if candidate and candidate.score >= self.min_score:
                candidates.append(candidate)
        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[:limit]

    def best_unambiguous(self, query: str) -> CatalogCandidate | None:
        candidates = self.search(query, limit=2)
        if not candidates:
            return None
        if len(candidates) > 1 and (candidates[0].score - candidates[1].score) < self.ambiguity_margin:
            return None
        return candidates[0]

    def _score_entry(self, query_norm: str, cid_codes: set[str], entry: dict[str, Any]) -> CatalogCandidate | None:
        fields = _entry_fields(entry)
        best_score = 0.0
        reasons: list[str] = []
        matched_fields: list[str] = []
        supporting_reasons: list[str] = []
        supporting_fields: list[str] = []

        entry_cids = {code.upper() for code in fields["cid10_codes"]}
        if cid_codes and cid_codes & entry_cids:
            best_score = 100.0
            reasons.append("cid_exact")
            matched_fields.append("cid10_codes")

        for field_name, values in fields.items():
            for value in values:
                field_norm = normalize_text_for_match(value)
                if not field_norm:
                    continue
                relevance = _substring_relevance(query_norm, field_norm)
                if _contains_complete_field(query_norm, field_norm):
                    score = 100.0
                    support_score = score
                    reason = "field_exact"
                elif relevance >= 0.55:
                    score = 92.0 + min(7.0, relevance * 7.0)
                    support_score = score
                    reason = "field_substring"
                else:
                    fuzzy = _safe_ratio(query_norm, field_norm)
                    if len(query_norm.split()) == 1 and (len(field_norm.split()) > 1 or len(field_norm) <= 3):
                        fuzzy = 0
                    support_score = float(fuzzy)
                    score = float(fuzzy) if fuzzy >= self.min_score else 0.0
                    reason = "field_fuzzy"
                if score > best_score:
                    best_score = score
                    reasons = [reason]
                    matched_fields = [field_name]
                elif score == best_score and score:
                    reasons.append(reason)
                    matched_fields.append(field_name)
                if support_score >= 80:
                    supporting_reasons.append(f"supporting_{reason}")
                    supporting_fields.append(field_name)

        if best_score < self.min_score:
            return None
        reasons.extend(supporting_reasons)
        matched_fields.extend(supporting_fields)
        best_score += min(3.0, max(0, len(set(matched_fields)) - 1) * 0.5)
        disease = str(entry.get("disease") or entry.get("diretriz") or "").strip()
        diretriz = str(entry.get("diretriz") or disease).strip()
        return CatalogCandidate(
            diretriz=diretriz,
            disease=disease,
            disease_normalized=normalize_text_for_match(entry.get("disease_normalized") or disease),
            score=best_score,
            reasons=tuple(_dedupe(reasons)),
            matched_fields=tuple(_dedupe(matched_fields)),
            entry=entry,
        )


@lru_cache(maxsize=1)
def load_clinical_nlp_pipeline() -> Any | None:
    try:
        import spacy
        import medspacy

        # 1. Carregar o modelo base em Português
        nlp = spacy.load("pt_core_news_sm")

        # 2. Adicionar os componentes clínicos do medSpaCy
        return medspacy.load(nlp=nlp)
    except Exception as exc:
        _logger.debug("medspacy_unavailable; fallback nulo. erro=%s", exc)
        return None


def classify_clinical_intent(query: str) -> dict[str, Any]:
    query_norm = normalize_text_for_match(query)
    if not query_norm:
        return {"intent": None, "confidence": 0.0, "method": "embedding"}
    query_embedding = _char_ngram_embedding(query_norm)
    scored = []
    for intent, descriptions in INTENT_DESCRIPTIONS.items():
        score = max(_cosine_similarity(query_embedding, _char_ngram_embedding(description)) for description in descriptions)
        scored.append((intent, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    best_intent, best_score = scored[0]
    if best_score < 0.20:
        return {"intent": None, "confidence": round(best_score, 4), "method": "embedding"}
    return {"intent": best_intent, "confidence": round(best_score, 4), "method": "embedding"}


def detect_clinical_intent(query: str) -> str | None:
    return classify_clinical_intent(query)["intent"]


def extract_explicit_cid10_codes(query: str) -> list[str]:
    return _dedupe(code.upper() for code in CID10_RE.findall(query or ""))


def match_disease_from_catalog(query: str, catalog: Any, min_score: int = 90) -> dict[str, Any] | None:
    candidate = CatalogCandidateRetriever(catalog, min_score=min_score).best_unambiguous(query)
    if candidate is None:
        return None
    return {
        "name": candidate.disease,
        "normalized": candidate.disease_normalized,
        "confidence": round(min(1.0, candidate.score / 100.0), 4),
        "match_type": ",".join(candidate.reasons),
        "catalog_candidate": candidate.to_public_dict(),
        "catalog_entry": candidate.entry,
    }


def match_explicit_medications(query: str, catalog: Any, min_score: int = 90) -> list[dict[str, Any]]:
    query_norm = normalize_text_for_match(query)
    out: list[dict[str, Any]] = []
    for entry in _catalog_entries(catalog):
        for med in _as_list(entry.get("medicamentos")):
            med_norm = normalize_text_for_match(med)
            if not med_norm:
                continue
            score = 100 if _contains_complete_field(query_norm, med_norm) else _safe_ratio(query_norm, med_norm)
            if score >= min_score:
                out.append({"name": med, "normalized": med_norm, "confidence": round(score / 100.0, 4)})
    return _dedupe_dicts(out, key="normalized")


def _dedupe_dicts(values: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        item_key = str(value.get(key) or "")
        if not item_key or item_key in seen:
            continue
        seen.add(item_key)
        out.append(value)
    return out


def _clinical_terms_from_pipeline(query: str) -> tuple[list[str], list[str], list[str]]:
    nlp = load_clinical_nlp_pipeline()
    if nlp is None:
        return [], [], []
    try:
        doc = nlp(query)
    except Exception as exc:
        _logger.debug("clinical_nlp_failed; fallback vazio. erro=%s", exc)
        return [], [], []
    terms: list[str] = []
    negated: list[str] = []
    uncertain: list[str] = []
    for ent in getattr(doc, "ents", []) or []:
        text = str(getattr(ent, "text", "")).strip()
        if not text:
            continue
        terms.append(text)
        if bool(getattr(getattr(ent, "_", None), "is_negated", False)):
            negated.append(text)
        if bool(getattr(getattr(ent, "_", None), "is_uncertain", False)):
            uncertain.append(text)
    return _dedupe(terms), _dedupe(negated), _dedupe(uncertain)


def understand_clinical_query(query: str, conitec_catalog: Any | None = None) -> dict[str, Any]:
    original = str(query or "").strip()
    try:
        cid_codes = extract_explicit_cid10_codes(original)
        intent_result = classify_clinical_intent(original)
        candidates = CatalogCandidateRetriever(conitec_catalog).search(original, limit=5) if conitec_catalog else []
        disease = match_disease_from_catalog(original, conitec_catalog) if conitec_catalog else None
        medications = match_explicit_medications(original, conitec_catalog) if conitec_catalog else []

        # Prefer a dedicated clinical entity resolver when available.
        clinical_terms = []
        negated_terms = []
        uncertain_terms = []
        try:
            if ClinicalEntityResolver is not None:
                _cer = ClinicalEntityResolver()
                ents = _cer.extract_entities(original)
                clinical_terms = [e.get("text") for e in ents.get("entities", []) if e.get("text")]
            else:
                clinical_terms, negated_terms, uncertain_terms = _clinical_terms_from_pipeline(original)
        except Exception as exc:
            _logger.debug("clinical_entity_resolver_failed; fallback. erro=%s", exc)
            clinical_terms, negated_terms, uncertain_terms = _clinical_terms_from_pipeline(original)

        # If no disease matched yet, attempt to resolve detected entities against
        # the Conitec catalog using the specialized resolver (only for high
        # confidence matches). This keeps backward compatibility while moving
        # toward entity-linking based resolution.
        try:
            if not disease and conitec_catalog and clinical_terms and CatalogConceptResolver is not None:
                resolver = CatalogConceptResolver(conitec_catalog)
                resolved = resolver.resolve(clinical_terms, limit=3)
                # pick the first strong match (score >= 90)
                for ent_text, matches in resolved.items():
                    for m in matches:
                        if m.get("score", 0) >= 90:
                            # emulate previous match_disease_from_catalog output
                            disease = {
                                "name": m.get("disease") or m.get("diretriz"),
                                "normalized": normalize_text_for_match(m.get("disease") or m.get("diretriz") or ""),
                                "confidence": round(min(1.0, m.get("score", 0) / 100.0), 4),
                                "match_type": "entity_catalog_link",
                                "catalog_candidate": {"diretriz": m.get("diretriz"), "disease": m.get("disease"), "score": m.get("score")},
                                "catalog_entry": m.get("entry"),
                            }
                            break
                    if disease:
                        break
        except Exception as exc:
            _logger.debug("catalog_concept_resolver_failed; erro=%s", exc)
    except Exception as exc:
        _logger.warning("clinical_query_understanding_failed; usando fallback minimo. erro=%s", exc)
        cid_codes = extract_explicit_cid10_codes(original)
        intent_result = {"intent": None, "confidence": 0.0, "method": "embedding"}
        disease = None
        medications = []
        candidates = []
        clinical_terms, negated_terms, uncertain_terms = [], [], []

    clean_disease = None
    if disease:
        clean_disease = {k: v for k, v in disease.items() if k != "catalog_entry"}

    return {
        "original_query": original,
        "normalized_query": normalize_text_for_match(original),
        "intent": intent_result["intent"],
        "intent_result": intent_result,
        "detected_disease": clean_disease,
        "catalog_candidates": [candidate.to_public_dict() for candidate in candidates],
        "detected_cid10_codes": cid_codes,
        "detected_medications": medications,
        "detected_sections": INTENT_SECTION_LABELS.get(str(intent_result["intent"]), []),
        "clinical_terms": clinical_terms,
        "negated_terms": negated_terms,
        "uncertain_terms": uncertain_terms,
    }


def expand_query_for_medical_chat(
    understanding: dict[str, Any],
    catalog: Any | None = None,
    max_terms: int = 10,
) -> dict[str, Any]:
    original = str(understanding.get("original_query") or "").strip()
    # New strategy: expansion is controlled by detected canonical concepts and
    # the intent label. We do NOT add medications, CID codes or large catalog
    # dumps automatically. The catalog remains the source of truth for
    # canonical disease names.
    added: list[str] = []
    reasons: list[str] = []
    intent = understanding.get("intent")

    # Prefer an explicit detected disease (resolved against the catalog).
    disease_info = understanding.get("detected_disease") or {}
    disease_name = str(disease_info.get("name") or disease_info.get("diretriz") or "").strip()

    # If not resolved earlier, try to resolve short clinical terms against the
    # catalog now (conservative, unambiguous matches only). This helps cases
    # like "sgb" -> "Síndrome de Guillain-Barré" when the detector found
    # the short token but no catalog match was set upstream.
    if not disease_name and catalog:
        clinical_terms = understanding.get("clinical_terms") or []
        try:
            retriever = CatalogCandidateRetriever(catalog)
            for term in clinical_terms[:5]:
                if not term or len(term.strip()) < 2:
                    continue
                cand = retriever.best_unambiguous(term)
                if cand is not None:
                    disease_name = cand.disease or cand.diretriz
                    reasons.append("resolved_from_clinical_term")
                    break
        except Exception as exc:  # pragma: no cover - defensive
            _logger.debug("catalog_lookup_in_expansion_failed; erro=%s", exc)

    # As a last conservative attempt, try matching the whole original query
    # against the catalog if nothing else produced a disease name. This is
    # intentional and conservative: we only accept an unambiguous best match.
    if not disease_name and catalog:
        try:
            retriever = CatalogCandidateRetriever(catalog)
            cand = retriever.best_unambiguous(original)
            if cand is not None:
                disease_name = cand.disease or cand.diretriz
                reasons.append("resolved_from_query")
        except Exception:
            pass

    if disease_name:
        added.append(disease_name)
        reasons.append("catalog_candidate")

    # Map intent to a compact label to guide retrieval (no heavy templating).
    if intent in TREATMENT_INTENTS:
        added.append("TRATAMENTO")
        reasons.append("intent_label")
    elif intent == "diagnostico":
        added.append("DIAGNÓSTICO")
        reasons.append("intent_label")
    elif intent == "monitoramento":
        added.append("MONITORAMENTO")
        reasons.append("intent_label")
    elif intent == "criterios_inclusao":
        added.append("CRITÉRIOS DE INCLUSÃO")
        reasons.append("intent_label")
    elif intent == "criterios_exclusao":
        added.append("CRITÉRIOS DE EXCLUSÃO")
        reasons.append("intent_label")

    # Also include any explicit section candidates detected by the classifier.
    for section in understanding.get("detected_sections") or []:
        added.append(section)
        reasons.append("intent_label")

    # Add helpful contextual tokens for pediatric / diagnostic queries when the
    # original query mentions children or pediatric context. Keep additions
    # small and relevant to avoid polluting retrieval.
    original_norm = normalize_text_for_match(original)
    child_indicators = ("crian", "pediatr", "infantil", "adolesc")
    if any(tok in original_norm for tok in child_indicators):
        # include both generic and domain words that improve pediatric recall
        added.extend(["criança", "pediátrico"])
        reasons.extend(["context_child", "context_child"])

    # For diagnostic-intent queries, include diagnostic-oriented terms that
    # help retrieve manifestations, criteria and clinical descriptions.
    if intent == "diagnostico":
        # only add these when not already present to keep expansion concise
        diag_tokens = ["DIAGNÓSTICO", "manifestações clínicas", "sinais e sintomas"]
        for t in diag_tokens:
            added.append(t)
            reasons.append("intent_diagnostic_token")

    added_terms = _dedupe(added, limit=max(0, int(max_terms)))
    expanded_query = "\n".join([original] + added_terms) if added_terms else original
    return {
        "original_query": original,
        "expanded_query": expanded_query,
        "added_terms": added_terms,
        "expansion_reason": _dedupe(reasons),
    }
