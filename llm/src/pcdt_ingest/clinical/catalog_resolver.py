"""Catalog-aware clinical concept resolution for Conitec entries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import logging
from typing import Any, Iterable

from pcdt_ingest.reference_data.conitec_catalog import normalize_text_for_match, read_catalog_jsonl

_logger = logging.getLogger("pcdt_ingest.clinical.catalog_resolver")


@dataclass(frozen=True)
class CatalogCandidate:
    diretriz: str
    disease: str
    score: float
    matched_fields: list[str]
    reasons: list[str]
    source: str
    entry: dict[str, Any]

    def to_dict(self, *, include_entry: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if not include_entry:
            data.pop("entry", None)
        return data


class CatalogConceptResolver:
    """Resolve linked entities and/or the original query against Conitec."""

    def __init__(self, catalog: Any | None = None, *, catalog_path=None, min_score: float = 0.84) -> None:
        if catalog is None and catalog_path is not None:
            try:
                self.catalog = read_catalog_jsonl(catalog_path)
            except Exception:
                self.catalog = {}
        else:
            self.catalog = catalog or {}
        self.min_score = min_score
        self._token_df: dict[str, int] | None = None
        try:
            from rapidfuzz import fuzz

            self._fuzz = fuzz
        except Exception:
            self._fuzz = None

    def resolve(
        self,
        query: str | Iterable[str],
        linked_entities: list[Any] | None = None,
        intent: Any | None = None,
        *,
        limit: int = 5,
    ) -> list[CatalogCandidate] | dict[str, list[dict[str, Any]]]:
        if not isinstance(query, str):
            legacy: dict[str, list[dict[str, Any]]] = {}
            for name in query:
                candidates = self.resolve(str(name), [], intent, limit=limit)
                legacy[str(name)] = [candidate.to_dict(include_entry=True) for candidate in candidates]  # type: ignore[union-attr]
            return legacy

        candidates: list[CatalogCandidate] = []
        for entry in self._entries():
            scored = self._score_entry(query, linked_entities or [], entry)
            if scored and scored.score >= self.min_score:
                candidates.append(scored)
        candidates.sort(key=lambda item: item.score, reverse=True)
        return self._demote_ambiguous(candidates[:limit])

    def _entries(self) -> list[dict[str, Any]]:
        if isinstance(self.catalog, dict):
            return [entry for entry in self.catalog.values() if isinstance(entry, dict)]
        try:
            return [entry for entry in self.catalog if isinstance(entry, dict)]
        except Exception:
            return []

    def _score_entry(self, query: str, linked_entities: list[Any], entry: dict[str, Any]) -> CatalogCandidate | None:
        query_norm = normalize_text_for_match(query)
        phrases = [(query, "catalog_semantic", 0.0)]
        for entity in linked_entities:
            if isinstance(entity, dict):
                text = entity.get("canonical") or entity.get("text") or ""
                confidence = float(entity.get("confidence") or 0.0)
            else:
                text = getattr(entity, "canonical", "") or getattr(entity, "text", "")
                confidence = float(getattr(entity, "confidence", 0.0) or 0.0)
            if text:
                phrases.append((str(text), "linked_entity", confidence))

        best = 0.0
        best_source = "catalog_semantic"
        matched_fields: list[str] = []
        reasons: list[str] = []
        supporting_fields: list[str] = []
        supporting_reasons: list[str] = []
        for phrase, source, entity_confidence in phrases:
            phrase_norm = normalize_text_for_match(phrase)
            if not phrase_norm:
                continue
            entry_signal = self._entry_semantic_score(query_norm, phrase_norm, entry, source)
            if source == "linked_entity":
                entry_signal = (
                    entry_signal[0] * max(0.75, min(1.0, entity_confidence or 0.9)),
                    entry_signal[1],
                    entry_signal[2],
                )
            if entry_signal[0] > best:
                best = entry_signal[0]
                best_source = source
                matched_fields = entry_signal[1]
                reasons = entry_signal[2]
            elif entry_signal[0] == best and best > 0:
                matched_fields.extend(entry_signal[1])
                reasons.extend(entry_signal[2])
            if entry_signal[0] >= self.min_score:
                supporting_fields.extend(entry_signal[1])
                supporting_reasons.extend(entry_signal[2])

            for field, value in self._fields(entry):
                field_norm = normalize_text_for_match(value)
                if not field_norm:
                    continue
                score, reason = self._field_score(query_norm, phrase_norm, field_norm, field)
                if source == "linked_entity":
                    score *= max(0.75, min(1.0, entity_confidence or 0.9))
                if score > best:
                    best = score
                    best_source = source
                    matched_fields = [field]
                    reasons = [reason]
                elif score == best and score > 0:
                    matched_fields.append(field)
                    reasons.append(reason)
                if score >= self.min_score:
                    supporting_fields.append(field)
                    supporting_reasons.append(reason)

        if best <= 0:
            return None
        disease = str(entry.get("disease") or entry.get("diretriz") or "").strip()
        diretriz = str(entry.get("diretriz") or disease).strip()
        return CatalogCandidate(
            diretriz=diretriz,
            disease=disease,
            score=round(min(1.0, best), 4),
            matched_fields=_dedupe([*matched_fields, *supporting_fields]),
            reasons=_dedupe([*reasons, *supporting_reasons]),
            source=best_source,
            entry=entry,
        )

    def _entry_semantic_score(
        self,
        query_norm: str,
        phrase_norm: str,
        entry: dict[str, Any],
        source: str,
    ) -> tuple[float, list[str], list[str]]:
        query_tokens = _tokens(phrase_norm)
        if not query_tokens:
            return 0.0, [], []

        concept_fields = {
            "disease",
            "disease_normalized",
            "diretriz",
            "diretriz_normalized",
            "descricao_siglas",
            "source_stem",
            "source_pdf",
            "derived_acronym",
        }
        fields = [(field, value) for field, value in self._fields(entry) if field in concept_fields]
        field_tokens_by_name: dict[str, set[str]] = {}
        for field, value in fields:
            field_tokens_by_name.setdefault(field, set()).update(_tokens(value))

        all_field_tokens: set[str] = set()
        for tokens in field_tokens_by_name.values():
            all_field_tokens.update(tokens)

        shared = query_tokens & all_field_tokens
        prefix_shared = _prefix_overlap(query_tokens - shared, all_field_tokens - shared)
        matched_tokens = shared | prefix_shared
        if not matched_tokens:
            return 0.0, [], []

        df = self._token_document_frequency()
        rare_matches = {token for token in matched_tokens if df.get(token, 0) <= 1}
        common_matches = matched_tokens - rare_matches
        if len(matched_tokens) < 2:
            single_match = next(iter(matched_tokens))
            if not rare_matches or not _is_single_token_concept_anchor(single_match, fields):
                return 0.0, [], ["weak_single_catalog_context_match"]
        query_weight = sum(1.0 / max(1, df.get(token, 1)) for token in query_tokens)
        match_weight = sum(1.0 / max(1, df.get(token, 1)) for token in matched_tokens)
        weighted_coverage = match_weight / max(query_weight, 0.0001)

        if len(query_tokens) == 1 and not rare_matches:
            return 0.0, [], ["ambiguous_single_catalog_token"]

        score = 0.70 + min(0.28, weighted_coverage * 0.28)
        if rare_matches:
            score += 0.08
        if source == "linked_entity":
            score += 0.04
        score = min(0.98, score)

        if score < self.min_score and not rare_matches:
            return 0.0, [], ["weak_catalog_semantic_overlap"]

        matched_fields = [
            field for field, tokens in field_tokens_by_name.items() if tokens & matched_tokens or _prefix_overlap(query_tokens, tokens)
        ]
        reasons = ["catalog_semantic_overlap"]
        if rare_matches:
            reasons.append("rare_catalog_token_match")
        if common_matches:
            reasons.append("common_catalog_token_support")
        return score, _dedupe(matched_fields), reasons

    def _field_score(self, query_norm: str, phrase_norm: str, field_norm: str, field: str) -> tuple[float, str]:
        if phrase_norm == field_norm:
            return 1.0, "field_exact"
        if _contains_phrase(query_norm, field_norm):
            if field in {"descricao_siglas", "derived_acronym"}:
                return 0.88, "field_in_query"
            return 0.98, "field_in_query"
        query_tokens = _tokens(query_norm)
        field_tokens = _tokens(field_norm)
        if field == "derived_acronym" and field_norm in query_tokens:
            return 0.96, "derived_acronym"
        if len(_tokens(phrase_norm)) <= 1:
            return 0.0, "weak_single_term"
        if _contains_phrase(field_norm, phrase_norm):
            coverage = len(phrase_norm) / max(1, len(field_norm))
            if field == "source_stem" and phrase_norm in field_norm.split():
                return 0.94, "source_stem_term"
            if coverage >= 0.28:
                return 0.86 + min(0.1, coverage / 5), "field_contains_phrase"
        if field == "cid10_codes" and phrase_norm.upper() == field_norm.upper():
            return 1.0, "cid10"
        fuzzy = self._ratio(phrase_norm, field_norm)
        if len(phrase_norm.split()) <= 1 and not _contains_phrase(field_norm, phrase_norm):
            return 0.0, "weak_single_term"
        if fuzzy >= 0.90:
            return fuzzy, "field_fuzzy"
        return 0.0, "no_match"

    def _fields(self, entry: dict[str, Any]) -> Iterable[tuple[str, str]]:
        for field in (
            "disease",
            "disease_normalized",
            "diretriz",
            "diretriz_normalized",
            "cid10_codes",
            "cid10_descriptions",
            "medicamentos",
            "descricao_siglas",
            "source_stem",
            "source_pdf",
        ):
            for value in _as_list(entry.get(field)):
                yield field, value
        for field in ("disease", "diretriz"):
            for value in _as_list(entry.get(field)):
                acronym = _acronym(value)
                if acronym:
                    yield "derived_acronym", acronym

    def _ratio(self, a: str, b: str) -> float:
        if self._fuzz is not None:
            try:
                return max(
                    self._fuzz.WRatio(a, b),
                    self._fuzz.token_sort_ratio(a, b),
                    self._fuzz.token_set_ratio(a, b),
                ) / 100.0
            except Exception:
                pass
        return SequenceMatcher(None, a, b).ratio()

    def _token_document_frequency(self) -> dict[str, int]:
        if self._token_df is not None:
            return self._token_df
        df: dict[str, int] = {}
        for entry in self._entries():
            tokens: set[str] = set()
            for _field, value in self._fields(entry):
                tokens.update(_tokens(value))
            for token in tokens:
                df[token] = df.get(token, 0) + 1
        self._token_df = df
        return df

    def _demote_ambiguous(self, candidates: list[CatalogCandidate]) -> list[CatalogCandidate]:
        if len(candidates) < 2:
            return candidates
        if candidates[0].score - candidates[1].score >= 0.04:
            return candidates
        return [
            CatalogCandidate(
                diretriz=c.diretriz,
                disease=c.disease,
                score=round(min(c.score, 0.74), 4),
                matched_fields=c.matched_fields,
                reasons=_dedupe([*c.reasons, "ambiguous_close_candidates"]),
                source=c.source,
                entry=c.entry,
            )
            for c in candidates
        ]


def _contains_phrase(haystack: str, needle: str) -> bool:
    return bool(haystack and needle and f" {needle} " in f" {haystack} ")


def _tokens(value: str) -> set[str]:
    return {token for token in normalize_text_for_match(value).split() if len(token) >= 4}


def _prefix_overlap(left: set[str], right: set[str]) -> set[str]:
    out: set[str] = set()
    for token in left:
        if len(token) < 5:
            continue
        stem = token[:5]
        if any(other.startswith(stem) or stem.startswith(other[:5]) for other in right if len(other) >= 5):
            out.add(token)
    return out


def _is_single_token_concept_anchor(token: str, fields: Iterable[tuple[str, str]]) -> bool:
    """Allow a single rare token only when it anchors the catalog concept itself."""
    stem = token[:5] if len(token) >= 5 else token
    for field, value in fields:
        tokens = [item for item in normalize_text_for_match(value).split() if len(item) >= 4]
        if not tokens:
            continue
        if field in {"disease", "disease_normalized", "diretriz", "diretriz_normalized"}:
            first = tokens[0]
            if first == token or (len(stem) >= 5 and first.startswith(stem)):
                return True
        if field in {"descricao_siglas", "derived_acronym"}:
            if token in tokens or (len(stem) >= 5 and any(item.startswith(stem) for item in tokens)):
                return True
    return False


def _acronym(value: str) -> str:
    tokens = [token for token in normalize_text_for_match(value).split() if len(token) > 2]
    if len(tokens) < 2:
        return ""
    acronym = "".join(token[0] for token in tokens[:6])
    return acronym if len(acronym) >= 3 else ""


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = normalize_text_for_match(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out
