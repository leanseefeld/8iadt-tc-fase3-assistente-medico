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


@lru_cache(maxsize=1)
def _load_spacy_pipeline() -> tuple[Any | None, str]:
    """Load medSpaCy/spaCy when installed. Never downloads models at runtime."""
    try:
        import medspacy

        nlp = medspacy.load("pt_core_news_sm")
        return nlp, "medspacy"
    except Exception as exc:
        _logger.debug("medspacy_entity_resolver_unavailable; erro=%s", exc)

    try:
        import spacy
        return spacy.load("pt_core_news_sm"), "spacy"
    except Exception as exc:
        _logger.debug("spacy_entity_resolver_unavailable; erro=%s", exc)
    return None, "none"


def resolve_clinical_entities(
    query: str,
    *,
    catalog: Any | None = None,
    intent: dict[str, Any] | None = None,
    catalog_limit: int = 5,
) -> dict[str, Any]:
    """Extract clinical entities with optional medSpaCy/spaCy and catalog fallback."""
    text = str(query or "").strip()
    entities: list[dict[str, Any]] = []
    backend_used = "none"
    nlp, backend = _load_spacy_pipeline()
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
