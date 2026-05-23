"""Optional biomedical entity extraction and linking.

The resolver never downloads models at runtime and never invents entities from
query tokens. If no biomedical backend is installed, it returns an empty list.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
import os
from typing import Any

_logger = logging.getLogger("pcdt_ingest.clinical.entity_resolver")


@dataclass(frozen=True)
class LinkedEntity:
    text: str
    canonical: str
    cui: str
    semantic_types: list[str]
    confidence: float
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BiomedicalEntityResolver:
    """Extract linked biomedical entities with optional installed backends."""

    def __init__(self) -> None:
        self._backend = "none"
        self._nlp = None
        self._quickumls = None
        self._load_backend()

    @property
    def backend(self) -> str:
        return self._backend

    def extract_and_link(self, query: str) -> list[LinkedEntity]:
        text = str(query or "").strip()
        if not text:
            return []
        if self._quickumls is not None:
            return self._extract_quickumls(text)
        if self._nlp is not None:
            return self._extract_spacy(text)
        _logger.debug("biomedical_entity_resolver_unavailable")
        return []

    def _load_backend(self) -> None:
        if self._try_load_scispacy():
            return
        if self._try_load_quickumls():
            return
        self._try_load_spacy_ner()

    def _try_load_scispacy(self) -> bool:
        try:
            import spacy

            model_names = _configured_model_names("BIOMEDICAL_SPACY_MODEL", ("pt_core_sci_sm", "en_core_sci_sm"))
            for model_name in model_names:
                try:
                    nlp = spacy.load(model_name)
                    if "scispacy_linker" not in nlp.pipe_names:
                        try:
                            nlp.add_pipe("scispacy_linker", config={"resolve_abbreviations": True})
                        except Exception:
                            pass
                    self._nlp = nlp
                    self._backend = "scispacy"
                    _logger.info("biomedical_entity_backend=scispacy model=%s", model_name)
                    return True
                except Exception:
                    continue
        except Exception:
            return False
        return False

    def _try_load_quickumls(self) -> bool:
        try:
            from quickumls import QuickUMLS

            quickumls_path = os.getenv("QUICKUMLS_FP") or os.getenv("QUICKUMLS_PATH")
            if not quickumls_path:
                return False
            self._quickumls = QuickUMLS(quickumls_path)
            self._backend = "quickumls"
            _logger.info("biomedical_entity_backend=quickumls")
            return True
        except Exception:
            return False

    def _try_load_spacy_ner(self) -> bool:
        try:
            import spacy

            model_names = _configured_model_names("CLINICAL_NER_SPACY_MODEL", ("pt_core_news_sm", "en_core_web_sm"))
            for model_name in model_names:
                try:
                    self._nlp = spacy.load(model_name)
                    self._backend = "spacy"
                    _logger.info("biomedical_entity_backend=spacy model=%s", model_name)
                    return True
                except Exception:
                    continue
        except Exception:
            return False
        return False

    def _extract_quickumls(self, text: str) -> list[LinkedEntity]:
        out: list[LinkedEntity] = []
        try:
            matches = self._quickumls.match(text, best_match=True, ignore_syntax=False) or []
        except Exception as exc:
            _logger.debug("quickumls_failed; erro=%s", exc)
            return []
        for group in matches:
            items = group if isinstance(group, list) else [group]
            for item in items:
                term = str(item.get("term") or item.get("ngram") or "").strip()
                if not term:
                    continue
                out.append(
                    LinkedEntity(
                        text=str(item.get("ngram") or term),
                        canonical=term,
                        cui=str(item.get("cui") or ""),
                        semantic_types=[str(st) for st in item.get("semtypes") or []],
                        confidence=float(item.get("similarity") or 0.0),
                        source="quickumls",
                    )
                )
        return _dedupe_entities(out)

    def _extract_spacy(self, text: str) -> list[LinkedEntity]:
        try:
            doc = self._nlp(text)
        except Exception as exc:
            _logger.debug("spacy_ner_failed; erro=%s", exc)
            return []
        out: list[LinkedEntity] = []
        linker_pipe = None
        if self._backend == "scispacy":
            try:
                linker_pipe = self._nlp.get_pipe("scispacy_linker")
            except Exception:
                linker_pipe = None
        for ent in getattr(doc, "ents", []) or []:
            ent_text = str(getattr(ent, "text", "")).strip()
            if not ent_text:
                continue
            canonical = ent_text
            cui = ""
            confidence = 0.75 if self._backend == "spacy" else 0.9
            semantic_types = [str(getattr(ent, "label_", ""))]
            kb_ents = getattr(getattr(ent, "_", None), "kb_ents", None) or []
            if kb_ents and self._backend == "scispacy":
                cui = str(kb_ents[0][0])
                confidence = float(kb_ents[0][1])
                canonical = _scispacy_canonical_name(linker_pipe, cui) or canonical
            out.append(
                LinkedEntity(
                    text=ent_text,
                    canonical=canonical,
                    cui=cui,
                    semantic_types=[item for item in semantic_types if item],
                    confidence=confidence,
                    source=self._backend,
                )
            )
        return _dedupe_entities(out)


def _dedupe_entities(values: list[LinkedEntity]) -> list[LinkedEntity]:
    out: list[LinkedEntity] = []
    seen: set[tuple[str, str, str]] = set()
    for value in values:
        key = (value.text.lower(), value.canonical.lower(), value.cui)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _configured_model_names(env_name: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
    configured = [item.strip() for item in (os.getenv(env_name) or "").split(",") if item.strip()]
    return tuple(configured) if configured else defaults


def _scispacy_canonical_name(linker_pipe: Any, cui: str) -> str:
    if not linker_pipe or not cui:
        return ""
    try:
        entity = linker_pipe.kb.cui_to_entity.get(cui)
    except Exception:
        return ""
    return str(getattr(entity, "canonical_name", "") or "").strip()
