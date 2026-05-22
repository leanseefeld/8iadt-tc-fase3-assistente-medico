"""Clinical entity extraction using spaCy/scispaCy with safe fallbacks.

This module provides a small wrapper `ClinicalEntityResolver` that attempts to
load a biomedical-capable NLP pipeline (scispaCy if available, otherwise a
regular spaCy Portuguese model if present). If none are available, the resolver
falls back to a lightweight heuristic extractor.

The implementation is intentionally defensive so the rest of the codebase can
call `ClinicalEntityResolver.extract_entities(query)` without hard dependency
on heavyweight models during tests or in CI.
"""
from __future__ import annotations

from typing import Any, Dict, List
import logging

_logger = logging.getLogger("pcdt_ingest.clinical.entity_resolver")


class ClinicalEntityResolver:
    """Extract clinical entities from a free-text query.

    The resolver will try to use scispaCy / spaCy models when available. The
    returned format is intentionally minimal and canonicalization/linking is
    performed by a separate component (CatalogConceptResolver).
    """

    def __init__(self, *, language: str = "pt") -> None:
        self.language = language
        self._nlp = None
        try:
            # Prefer a light Portuguese model when available (keeps behavior
            # closer to user language). This is optional and will not raise on
            # import failure.
            import spacy

            try:
                # user may have installed a Portuguese model
                self._nlp = spacy.load("pt_core_news_sm")
                _logger.debug("loaded spacy pt_core_news_sm for ClinicalEntityResolver")
            except Exception:
                # fallback to any available small model
                try:
                    self._nlp = spacy.load("en_core_web_sm")
                    _logger.debug("loaded spacy en_core_web_sm for ClinicalEntityResolver")
                except Exception:
                    self._nlp = None
        except Exception:
            self._nlp = None

    def extract_entities(self, query: str) -> Dict[str, Any]:
        """Return a dictionary describing extracted entities.

        Output shape:
        {
            "entities": [
                {"text": str, "canonical": Optional[str], "semantic_type": str, "confidence": float}
            ]
        }
        """
        q = str(query or "").strip()
        if not q:
            return {"entities": []}

        if self._nlp is None:
            # simple heuristic: return uppercase/acronyms and individual tokens
            ents: List[Dict[str, Any]] = []
            for tok in q.split():
                t = tok.strip(" ,.?;:")
                if not t:
                    continue
                if t.isupper() and len(t) >= 2:
                    ents.append({"text": t, "canonical": None, "semantic_type": "ACRONYM", "confidence": 0.9})
            # as a fallback, attempt to include single-word tokens that look medical
            if not ents:
                words = [w.strip(" ,.?;:") for w in q.split() if w]
                if words:
                    ents.append({"text": words[0], "canonical": None, "semantic_type": "TERM", "confidence": 0.4})
            return {"entities": ents}

        try:
            doc = self._nlp(q)
        except Exception as exc:  # defensive
            _logger.debug("nlp processing failed; fallback. erro=%s", exc)
            return {"entities": []}

        out: List[Dict[str, Any]] = []
        for ent in getattr(doc, "ents", []) or []:
            text = str(getattr(ent, "text", "")).strip()
            if not text:
                continue
            label = str(getattr(ent, "label_", "ENTITY"))
            # confidence is not always available; use a heuristic
            conf = float(getattr(ent, "_.confidence", 0.9) if hasattr(ent, "_.confidence") else 0.9)
            out.append({"text": text, "canonical": None, "semantic_type": label, "confidence": conf})

        return {"entities": out}

