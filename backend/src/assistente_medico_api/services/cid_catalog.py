"""In-memory CID-10 catalog used by /api/cids."""

from __future__ import annotations

from functools import lru_cache

from assistente_medico_api.schemas.cids import Cid

try:
    import simple_icd_10 as icd10
except Exception:  # pragma: no cover - fallback keeps endpoint working.
    icd10 = None


_FALLBACK_CID_LIST: list[Cid] = [
    Cid(code="L40.5",   label="Artrite Psoriásica"),
    Cid(code="A41.9",   label="Sepse não especificada"),
    Cid(code="T81.4",   label="Infecção pós-procedimento cirúrgico"),
    Cid(code="E11.9",   label="Diabetes Mellitus tipo 2 sem complicações"),
    Cid(code="I10",     label="Hipertensão Essencial"),
    Cid(code="J18.9",   label="Pneumonia não especificada"),
    Cid(code="N17.9",   label="Insuficiência Renal Aguda"),
    Cid(code="K92.1",   label="Melena"),
    Cid(code="I63.9",   label="AVC Isquêmico"),
    Cid(code="M05.3",   label="Artrite Reumatoide"),
    Cid(code="I50.0",   label="Insuficiência Cardíaca Congestiva"),
    Cid(code="B34.9",   label="Infecção viral não especificada"),
    Cid(code="R50.9",   label="Febre não especificada"),
    Cid(code="R06.02",  label="Dispneia de repouso"),
    Cid(code="D64.9",   label="Anemia não especificada"),
    Cid(code="E87.1",   label="Hiponatremia"),
    Cid(code="R57.0",   label="Choque cardiogênico"),
    Cid(code="T78.4",   label="Alergia não especificada"),
    Cid(code="Z87.891", label="História pessoal de alergia a medicamentos"),
    Cid(code="K85.9",   label="Pancreatite aguda"),
    Cid(code="C50.9",   label="Neoplasia maligna da mama"),
    Cid(code="G43.9",   label="Enxaqueca"),
]


def _is_selectable_cid_code(code: str) -> bool:
    # Excludes chapter labels (e.g. "I") and range buckets (e.g. "A00-A09").
    if "-" in code or len(code) < 3:
        return False
    return code[0].isalpha() and code[1].isdigit() and code[2].isdigit()


@lru_cache(maxsize=1)
def _build_cid_list() -> tuple[Cid, ...]:
    if icd10 is None:
        return tuple(_FALLBACK_CID_LIST)

    items: list[Cid] = []
    seen: set[str] = set()
    for code in icd10.get_all_codes(with_dots=True):
        if not _is_selectable_cid_code(code) or code in seen:
            continue
        description = (icd10.get_description(code) or "").strip()
        if not description:
            continue
        seen.add(code)
        items.append(Cid(code=code, label=description))

    if not items:
        return tuple(_FALLBACK_CID_LIST)
    return tuple(items)


# Constant kept at module import time for fast read-only endpoint usage.
CID_LIST: list[Cid] = list(_build_cid_list())


def list_cids() -> list[Cid]:
    return CID_LIST
