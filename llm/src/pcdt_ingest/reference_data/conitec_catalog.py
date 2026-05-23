"""Catálogo canônico Conitec para enriquecer metadados dos chunks PCDT."""

from __future__ import annotations

import io
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import httpx
import pandas as pd

CONITEC_CATALOG_URL = (
    "https://www.gov.br/conitec/pt-br/midias/dados-em-excel/"
    "medicamentos_cid_pcdt_atual-1.xlsx/@@download/file"
)

DEFAULT_CATALOG_RELATIVE_PATH = Path("processed") / "conitec" / "pcdt_catalog.jsonl"

COLUMN_RENAMES = {
    "Formato": "formato",
    "Diretriz": "diretriz",
    "Código da CID-10": "cid10_code",
    "Descrição do Código da CID-10": "cid10_description",
    "Medicamento": "medicamento",
    "Portaria da Diretriz": "portaria_diretriz",
    "Data da Portaria": "data_portaria",
    "Descrição das Siglas": "descricao_siglas",
}

GENERIC_SOURCE_TOKENS = {
    "pcdt",
    "protocolo",
    "protocolos",
    "clinico",
    "clinicos",
    "diretriz",
    "diretrizes",
    "terapeutica",
    "terapeuticas",
    "relatorio",
    "portaria",
    "conjunta",
    "saes",
    "sctie",
    "ms",
    "ministerio",
    "saude",
    "conitec",
    "atualizado",
    "final",
    "versao",
    "v",
    "a",
    "por",
    "portal",
    "associada",
    "associado",
    "associadas",
    "associados",
    "livro",
    "site",
    "tromb",
    "lise",
    "trombolise",
    "aij",
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
}

SOURCE_TEXT_REPAIRS = (
    (re.compile(r"\bisqu\s+mico\b", re.IGNORECASE), "isquemico"),
    (re.compile(r"\bdeficincia\b", re.IGNORECASE), "deficiencia"),
    (re.compile(r"\binsuficencia\b", re.IGNORECASE), "insuficiencia"),
    (re.compile(r"\bdoena\b", re.IGNORECASE), "doenca"),
    (re.compile(r"\bhidradernite\b", re.IGNORECASE), "hidradenite"),
    (re.compile(r"\bpcdthidradernite\b", re.IGNORECASE), "hidradenite"),
    (re.compile(r"\bdefici[eê]nciaferro\b", re.IGNORECASE), "deficiencia ferro"),
    (re.compile(r"\bdoencarenalcronica\b", re.IGNORECASE), "doenca renal cronica"),
    (re.compile(r"\bc1esterase\b", re.IGNORECASE), "c1 esterase"),
    (re.compile(r"\birc\b", re.IGNORECASE), "doenca renal cronica"),
)

SOURCE_DISEASE_ALIAS_NORMALIZED = {
    "sobrepeso obesidade adultos": "sobrepesso e obesidade em adultos",
    "insuficiencia adrenal": "insuficiencia adrenal",
    "trombofilia gestantes": "prevencao de tromboembolismo venoso em gestantes com trombofilia",
    "comportamento agressivo tea": "comportamento agressivo no transtorno do espectro do autismo",
    "lupus": "lupus eritematoso sistemico",
    "sindrome falencias medulares": "sindrome de falencia medular",
    "dmri": "degeneracao macular relacionada a idade",
    "dorcronica": "dor cronica",
    "hiperplasia adrenal congenita": "hiperplasia adrenal congenita",
    "imunodeficienciaprimaria": "imunodeficiencia primaria com predominancia de defeitos de anticorpos",
    "leiomioma": "leiomioma de utero",
    "paget": "doenca de paget",
    "hpn": "hemoglobinuria paroxistica noturna",
    "carcinomatireoide": "carcinoma diferenciado da tireoide",
    "deficienciadohormoniodecrescimento": "deficiencia do hormonio de crescimento hipopituitarismo",
    "hemangiomainfantil": "hemangioma infantil",
    "homocistinriaclassica": "homocistinuria classica",
    "imunossupressao pos transplante hepatico": "imunossupressao no transplante hepatico em adulto",
    "imunossupressonotransplantehepaticoempediatria": "imunossupressao no transplante hepatico em pediatria",
    "insuficienciapancreaticaexocrina fev2016": "insuficiencia pancreatica exocrina",
    "mucopolissacaridosetipovi": "mucopolissacaridose tipo vi",
    "sindromenefroticaprimaria criancasadolescentes": "sindrome nefrotica primaria em criancas e adolescentes",
    "transtornoafetivobipolar tipoi": "transtorno afetivo bipolar do tipo i",
    "trombocitopenia": "purpura trombocitopenica idiopatica",
    "diabete melito": "diabete melito tipo 1",
    "diabete melito tipo 2": "diabete melito tipo 2",
    "doenca pompe10": "doenca de pompe",
    "uveites": "uveites nao infecciosas",
    "portariaconjuntan14pcdttranstornododeficitdeatencaocomhiperatividadetdah": (
        "transtorno do deficit de atencao com hiperatividade"
    ),
    "portariaconjuntano8pcdtlipofuscinoseceroideneuronaltipo2": "lipofuscinose ceroide neuronal tipo 2",
    "manejo infeccao pelo hiv criancas adolescentes modulo 2 diagnostico manejo tratamento criancas adolescentes vivendo": (
        "manejo da infeccao pelo hiv em criancas e adolescentes modulo 2 diagnostico manejo e tratamento de "
        "criancas e adolescentes vivendo com hiv"
    ),
    "hidradenite supurativa": "hidradenite supurativa",
    "n glaucoma": "glaucoma",
}


def normalize_text_for_match(value: Any) -> str:
    """Normaliza texto para comparações robustas e determinísticas."""
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"(?<=[a-zà-ÿ])(?=[A-ZÀ-Ý])", " ", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\.pdf$", " ", text)
    text = re.sub(r"(?<!\d)(?:19|20)\d{6}(?!\d)", " ", text)
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_source_for_match(source_stem: str) -> str:
    """Normaliza nome de arquivo removendo datas e termos genéricos de PCDT."""
    text = normalize_text_for_match(source_stem)
    for pattern, replacement in SOURCE_TEXT_REPAIRS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"\b(?:19|20)\d{2}\b", " ", text)
    tokens: list[str] = []
    previous_kept: str | None = None
    for tok in text.split():
        if tok in GENERIC_SOURCE_TOKENS:
            continue
        if tok.isdigit() and previous_kept not in {"modulo", "tipo"}:
            continue
        tokens.append(tok)
        previous_kept = tok
    return " ".join(tokens)


def _clean_cell(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            value = value.date().isoformat()
        except Exception:
            value = str(value)
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _sorted_unique(values: Iterable[Any]) -> list[str]:
    cleaned = {_clean_cell(value) for value in values}
    return sorted(v for v in cleaned if v)


def load_conitec_xlsx(input_path_or_url: str | Path = CONITEC_CATALOG_URL) -> pd.DataFrame:
    """Carrega a planilha Conitec de caminho local ou URL explícita."""
    source = str(input_path_or_url)
    if source.startswith(("http://", "https://")):
        response = httpx.get(source, timeout=60.0, follow_redirects=True)
        response.raise_for_status()
        data: str | Path | io.BytesIO = io.BytesIO(response.content)
    else:
        data = Path(source)

    df = pd.read_excel(data, engine="openpyxl")
    return normalize_catalog_columns(df)


def normalize_catalog_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Renomeia colunas oficiais para snake_case e mantém as colunas conhecidas."""
    renamed = df.rename(columns=COLUMN_RENAMES).copy()
    expected = list(COLUMN_RENAMES.values())
    missing = [col for col in expected if col not in renamed.columns]
    if missing:
        raise ValueError(f"Planilha Conitec sem colunas esperadas: {', '.join(missing)}")
    return renamed[expected]


def build_catalog_by_diretriz(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Agrega linhas da planilha por diretriz."""
    normalized = normalize_catalog_columns(df) if "Diretriz" in df.columns else df.copy()
    out: dict[str, dict[str, Any]] = {}

    grouped = normalized.groupby("diretriz", dropna=True, sort=True)
    for diretriz, group in grouped:
        disease = _clean_cell(diretriz)
        if not disease:
            continue
        disease_normalized = normalize_text_for_match(disease)
        entry = {
            "disease": disease,
            "disease_normalized": disease_normalized,
            "diretriz": disease,
            "diretriz_normalized": disease_normalized,
            "formato": _sorted_unique(group["formato"]),
            "cid10_codes": _sorted_unique(group["cid10_code"]),
            "cid10_descriptions": _sorted_unique(group["cid10_description"]),
            "medicamentos": _sorted_unique(group["medicamento"]),
            "portarias": _sorted_unique(group["portaria_diretriz"]),
            "datas_portaria": _sorted_unique(group["data_portaria"]),
            "descricao_siglas": _sorted_unique(group["descricao_siglas"]),
        }
        out[disease_normalized] = entry
    return dict(sorted(out.items(), key=lambda item: item[0]))


def write_catalog_jsonl(catalog: dict[str, dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for key in sorted(catalog):
            f.write(json.dumps(catalog[key], ensure_ascii=False, sort_keys=True) + "\n")


def read_catalog_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            entry = json.loads(line)
            key = entry.get("diretriz_normalized") or entry.get("disease_normalized")
            if key:
                catalog[str(key)] = entry
    return dict(sorted(catalog.items(), key=lambda item: item[0]))


def build_and_write_catalog(input_path_or_url: str | Path, output_path: Path) -> dict[str, dict[str, Any]]:
    df = load_conitec_xlsx(input_path_or_url)
    catalog = build_catalog_by_diretriz(df)
    write_catalog_jsonl(catalog, output_path)
    return catalog


def _token_set(value: str) -> set[str]:
    return {tok for tok in normalize_source_for_match(value).split() if len(tok) > 1}


def _catalog_entry_tokens(entry: dict[str, Any]) -> set[str]:
    diretriz = str(entry.get("diretriz_normalized") or entry.get("diretriz") or "")
    return _token_set(diretriz)


def _score_candidate_tokens(source_tokens: set[str], target_tokens: set[str]) -> float | None:
    if not source_tokens or not target_tokens:
        return None
    overlap = source_tokens & target_tokens
    if not overlap:
        return None
    recall = len(overlap) / len(target_tokens)
    precision = len(overlap) / len(source_tokens)
    if source_tokens <= target_tokens and len(source_tokens) >= 2:
        return 0.90 + min(0.09, 0.01 * len(source_tokens))
    if target_tokens <= source_tokens and len(target_tokens) >= 2:
        return 0.86 + min(0.09, 0.01 * len(target_tokens))
    if recall >= 0.70 and precision >= 0.55 and len(overlap) >= 2:
        return (recall + precision) / 2
    return None


def _match_alias_target(source_norm: str, catalog: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    alias_target = SOURCE_DISEASE_ALIAS_NORMALIZED.get(source_norm)
    if not alias_target:
        return None
    return catalog.get(normalize_text_for_match(alias_target))


def match_source_to_disease(
    source_stem: str,
    catalog: dict[str, dict[str, Any]],
    *,
    candidate_texts: Iterable[str | None] = (),
) -> dict[str, Any] | None:
    """Associa um PDF a uma diretriz do catálogo; ausência de match é tratada como exceção."""
    raw_candidates = [source_stem, *(text for text in candidate_texts if text)]
    normalized_candidates = [normalize_source_for_match(text) for text in raw_candidates]
    normalized_candidates = [text for text in normalized_candidates if text]
    if not normalized_candidates:
        return None

    target_cache = [(entry, _catalog_entry_tokens(entry)) for entry in catalog.values()]
    for source_norm in normalized_candidates:
        for entry, target_tokens in target_cache:
            if source_norm == " ".join(sorted(target_tokens)):
                return entry
            diretriz_norm = normalize_source_for_match(str(entry.get("diretriz_normalized") or entry.get("diretriz") or ""))
            if source_norm == diretriz_norm:
                return entry

    for source_norm in normalized_candidates:
        alias_match = _match_alias_target(source_norm, catalog)
        if alias_match:
            return alias_match

    best_by_entry: dict[str, tuple[float, int, dict[str, Any]]] = {}
    for source_norm in normalized_candidates:
        source_tokens = _token_set(source_norm)
        for entry, target_tokens in target_cache:
            score = _score_candidate_tokens(source_tokens, target_tokens)
            if score is None:
                continue
            overlap = len(source_tokens & target_tokens)
            key = str(entry.get("diretriz_normalized") or entry.get("disease_normalized") or entry.get("diretriz"))
            current = best_by_entry.get(key)
            candidate = (score, overlap, entry)
            if current is None or (score, overlap) > (current[0], current[1]):
                best_by_entry[key] = candidate

    candidates = list(best_by_entry.values())
    if not candidates:
        for source_norm in normalized_candidates:
            alias_match = _match_alias_target(source_norm, catalog)
            if alias_match:
                return alias_match
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = candidates[0]
    if len(candidates) > 1 and best[0] - candidates[1][0] < 0.05:
        for source_norm in normalized_candidates:
            alias_match = _match_alias_target(source_norm, catalog)
            if alias_match:
                return alias_match
        return None
    return best[2]


def metadata_from_catalog_entry(entry: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "disease": entry.get("disease") or entry.get("diretriz"),
        "disease_normalized": entry.get("disease_normalized") or normalize_text_for_match(entry.get("disease")),
        "diretriz": entry.get("diretriz") or entry.get("disease"),
        "formato": entry.get("formato", []),
        "cid10_codes": entry.get("cid10_codes", []),
        "cid10_descriptions": entry.get("cid10_descriptions", []),
        "medicamentos": entry.get("medicamentos", []),
        "portarias": entry.get("portarias", []),
        "datas_portaria": entry.get("datas_portaria", []),
        "descricao_siglas": entry.get("descricao_siglas", []),
        "metadata_source": "conitec_xlsx",
    }
    for key in ("formato", "cid10_codes", "cid10_descriptions", "medicamentos", "portarias", "datas_portaria", "descricao_siglas"):
        values = meta.get(key)
        if not isinstance(values, list):
            values = [values] if values else []
        cleaned = _sorted_unique(values)
        meta[key] = cleaned
    return meta


def heuristic_metadata(disease: str | None) -> dict[str, Any]:
    return {
        "disease": disease,
        "disease_normalized": normalize_text_for_match(disease),
        "diretriz": None,
        "formato": [],
        "cid10_codes": [],
        "cid10_descriptions": [],
        "medicamentos": [],
        "portarias": [],
        "datas_portaria": [],
        "descricao_siglas": [],
        "metadata_source": "heuristic",
    }


def expand_query_terms(query: str, catalog: dict[str, dict[str, Any]], *, max_terms: int = 30) -> list[str]:
    """Expande uma pergunta com termos relacionados do catálogo Conitec."""
    query_norm = normalize_text_for_match(query)
    query_tokens = set(query_norm.split())
    matches: dict[str, None] = {}
    aliases: defaultdict[str, set[str]] = defaultdict(set)
    for entry in catalog.values():
        haystacks = [
            entry.get("diretriz", ""),
            entry.get("disease", ""),
            *entry.get("cid10_codes", []),
            *entry.get("cid10_descriptions", []),
            *entry.get("medicamentos", []),
            *entry.get("descricao_siglas", []),
        ]
        hay_norm = " ".join(normalize_text_for_match(item) for item in haystacks)
        hay_tokens = set(hay_norm.split())
        acronym_hits = {tok for tok in query_tokens if len(tok) >= 2 and tok in hay_tokens}
        substring_hit = bool(query_norm and query_norm in hay_norm)
        if not acronym_hits and not substring_hit:
            continue
        for field in ("diretriz", "disease"):
            value = _clean_cell(entry.get(field))
            if value:
                matches[value] = None
        for field in ("cid10_codes", "cid10_descriptions", "medicamentos", "descricao_siglas"):
            for value in entry.get(field, []):
                cleaned = _clean_cell(value)
                if cleaned:
                    aliases[field].add(cleaned)

    for field in ("cid10_codes", "cid10_descriptions", "medicamentos", "descricao_siglas"):
        for value in sorted(aliases[field]):
            matches[value] = None
            if len(matches) >= max_terms:
                return list(matches)
    return list(matches)[:max_terms]
