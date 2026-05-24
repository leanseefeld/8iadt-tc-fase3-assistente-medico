"""Optional clinical entity resolver used by rewrite/query understanding."""

from __future__ import annotations

from functools import lru_cache
import logging
from typing import Any

from assistente_medico_api.graph.clinical_query_understanding import (
    normalize_text_for_match,
    resolve_catalog_candidates,
)

_logger = logging.getLogger("assistente_medico.rag")


@lru_cache(maxsize=16)
def _load_spacy_pipeline(
    *,
    use_medspacy: bool,
    use_spacy: bool,
    medspacy_model: str,
    medspacy_language_code: str,
    spacy_model: str,
) -> tuple[Any | None, str]:
    """Load medSpaCy/spaCy when installed. Never downloads models at runtime."""
    if use_medspacy:
        try:
            import medspacy

            model = medspacy_model or "pt_core_news_sm"
            language_code = medspacy_language_code or "pt"
            _logger.info("entity_resolver: loading_medspacy model=%s language=%s", model, language_code)
            nlp = medspacy.load(model, language_code=language_code)
            _logger.info("entity_resolver: loaded_medspacy model=%s language=%s", model, language_code)
            return nlp, "medspacy"
        except Exception as exc:
            _logger.debug("medspacy_entity_resolver_unavailable; erro=%s", exc)

    if use_spacy:
        try:
            import spacy

            model = spacy_model or medspacy_model or "pt_core_news_sm"
            _logger.info("entity_resolver: loading_spacy model=%s", model)
            nlp = spacy.load(model)
            _logger.info("entity_resolver: loaded_spacy model=%s", model)
            return nlp, "spacy"
        except Exception as exc:
            _logger.debug("spacy_entity_resolver_unavailable; erro=%s", exc)
    return None, "none"


def resolve_clinical_entities(
    query: str,
    *,
    catalog: Any | None = None,
    intent: dict[str, Any] | None = None,
    catalog_limit: int = 5,
    enable_medical_nlp: bool = True,
    use_medspacy: bool = False,
    use_spacy: bool = True,
    medspacy_model: str = "pt_core_news_sm",
    medspacy_language_code: str = "pt",
    spacy_model: str = "pt_core_news_sm",
) -> dict[str, Any]:
    """Extract clinical entities with optional medSpaCy/spaCy and catalog fallback."""
    text = str(query or "").strip()
    entities: list[dict[str, Any]] = []
    backend_used = "disabled" if not enable_medical_nlp else "none"
    nlp = None
    backend = backend_used
    if enable_medical_nlp:
        nlp, backend = _load_spacy_pipeline(
            use_medspacy=use_medspacy,
            use_spacy=use_spacy,
            medspacy_model=medspacy_model,
            medspacy_language_code=medspacy_language_code,
            spacy_model=spacy_model,
        )
    if nlp is not None and text:
        backend_used = backend
        try:
            doc = nlp(text)
            for ent in getattr(doc, "ents", []) or []:
                ent_text = str(getattr(ent, "text", "") or "").strip()
                if not ent_text:
                    continue
                entities.append(
                    {
                        "text": ent_text,
                        "canonical": ent_text,
                        "source": backend,
                        "confidence": 0.78 if backend == "spacy" else 0.82,
                        "label": str(getattr(ent, "label_", "") or ""),
                    }
                )
        except Exception as exc:
            _logger.debug("clinical_entity_resolver_backend_failed; backend=%s erro=%s", backend, exc)
            backend_used = "none"

    catalog_candidates = resolve_catalog_candidates(text, catalog, entities, intent, limit=catalog_limit) if catalog else []
    fallback_entities = []
    for candidate in catalog_candidates:
        disease = str(candidate.get("disease") or candidate.get("diretriz") or "").strip()
        if not disease:
            continue
        fallback_entities.append(
            {
                "text": disease,
                "canonical": disease,
                "source": "catalog_fallback",
                "confidence": float(candidate.get("score") or 0.0),
            }
        )

    return {
        "linked_entities": _dedupe_entities([*entities, *fallback_entities]),
        "catalog_candidates": catalog_candidates,
        "medspacy_used": backend_used == "medspacy",
        "spacy_used": backend_used in {"spacy", "medspacy"},
        "entity_backend": backend_used,
        "medspacy_model": medspacy_model if backend_used == "medspacy" else None,
        "spacy_model": spacy_model if backend_used == "spacy" else None,
    }


def _dedupe_entities(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for value in values:
        key = (
            normalize_text_for_match(value.get("text") or ""),
            normalize_text_for_match(value.get("canonical") or ""),
            str(value.get("source") or ""),
        )
        if key in seen or not key[0]:
            continue
        seen.add(key)
        out.append(value)
    return out
