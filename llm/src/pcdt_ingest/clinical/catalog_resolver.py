"""Resolve candidate clinical concepts against the Conitec catalog.

This component is focused on mapping canonical disease names (strings) to the
catalog entries using RapidFuzz when available, falling back to a stable
sequence matcher otherwise.
"""
from __future__ import annotations

from typing import Any, Dict, List
import logging

from pcdt_ingest.reference_data.conitec_catalog import read_catalog_jsonl, normalize_text_for_match

_logger = logging.getLogger("pcdt_ingest.clinical.catalog_resolver")


class CatalogConceptResolver:
    """Resolve canonical concept names against the Conitec catalog.

    The resolver takes a loaded catalog (mapping normalized name -> entry) or a
    path to a JSONL file. The `resolve` method returns candidate matches with a
    score (0..100).
    """

    def __init__(self, catalog: Any | None = None, *, catalog_path=None) -> None:
        if catalog is None and catalog_path is not None:
            try:
                self.catalog = read_catalog_jsonl(catalog_path)
            except Exception:
                self.catalog = {}
        else:
            self.catalog = catalog or {}

        try:
            from rapidfuzz import fuzz

            self._fuzz = fuzz
        except Exception:
            self._fuzz = None

    def resolve(self, names: List[str], limit: int = 5) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        if isinstance(self.catalog, dict):
            entries = list(self.catalog.values())
        else:
            # assume catalog is a sequence of dicts
            try:
                entries = list(self.catalog)
            except Exception:
                entries = []
        for name in names:
            n_norm = normalize_text_for_match(name)
            candid = []
            if not n_norm:
                out[name] = []
                continue
            for entry in entries:
                target = str(entry.get("disease") or entry.get("diretriz") or "")
                target_norm = normalize_text_for_match(target)
                if not target_norm:
                    continue
                score = self._score(n_norm, target_norm)
                if score is None:
                    continue
                candid.append({"diretriz": entry.get("diretriz"), "disease": entry.get("disease"), "score": score, "entry": entry})
            candid.sort(key=lambda x: x["score"], reverse=True)
            out[name] = candid[:limit]
        return out

    def _score(self, a: str, b: str) -> int | None:
        if self._fuzz is not None:
            try:
                # use a robust weighted ratio when available
                return int(max(self._fuzz.WRatio(a, b), self._fuzz.token_sort_ratio(a, b), self._fuzz.token_set_ratio(a, b)))
            except Exception:
                pass
        # fallback
        from difflib import SequenceMatcher

        r = int(SequenceMatcher(None, a, b).ratio() * 100)
        return r if r >= 30 else None

