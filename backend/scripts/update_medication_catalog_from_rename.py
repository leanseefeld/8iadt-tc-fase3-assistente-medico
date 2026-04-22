"""Update medication catalog from RENAME 2024 PDF DCB column."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

try:
    import pdfplumber
except ImportError as exc:  # pragma: no cover - runtime guard
    raise SystemExit(
        "Dependencia ausente: pdfplumber. Instale com: pip install pdfplumber"
    ) from exc

ATC_CODE_RE = re.compile(r"^[A-Z][0-9]{2}[A-Z0-9]{1,5}$")
RENAME_TAG = "RENAME-2024"


@dataclass
class CatalogEntry:
    code: str
    label: str
    active_ingredient: str
    source_tags: list[str]


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description=(
            "Extrai nomes da coluna DCB do PDF rename-medicamentos-2024.pdf "
            "e atualiza medication_catalog.py sem duplicidades."
        )
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=repo_root / "docs" / "rename-medicamentos-2024.pdf",
        help="Caminho para o arquivo rename-medicamentos-2024.pdf",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=repo_root
        / "backend"
        / "src"
        / "assistente_medico_api"
        / "services"
        / "medication_catalog.py",
        help="Caminho para o medication_catalog.py a ser atualizado",
    )
    return parser.parse_args()


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def ascii_fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_key(text: str) -> str:
    base = ascii_fold(text).lower()
    base = re.sub(r"[^a-z0-9+]+", " ", base)
    return normalize_space(base)


def normalize_header(cell: str | None) -> str:
    if not cell:
        return ""
    return normalize_space(ascii_fold(cell)).lower()


def sanitize_dcb_name(raw_name: str) -> str:
    text = normalize_space(raw_name.replace("\n", " ").replace("•", " "))
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\*+$", "", text).strip()
    text = ascii_fold(text)
    text = normalize_space(text)
    if not text:
        return ""
    return text[0].upper() + text[1:]


def ensure_rename_tag(entry: CatalogEntry) -> None:
    if RENAME_TAG in entry.source_tags:
        return
    entry.source_tags.append(RENAME_TAG)


def generate_code(label: str, used_codes: set[str]) -> str:
    candidate = ascii_fold(label).upper().replace("+", " MAIS ")
    candidate = re.sub(r"[^A-Z0-9]+", "_", candidate)
    candidate = re.sub(r"_+", "_", candidate).strip("_")
    if not candidate:
        candidate = "MEDICAMENTO"
    if candidate[0].isdigit():
        candidate = f"MED_{candidate}"

    code = candidate
    suffix = 2
    while code in used_codes:
        code = f"{candidate}_{suffix}"
        suffix += 1
    used_codes.add(code)
    return code


def extract_dcb_names(pdf_path: Path) -> list[str]:
    names: list[str] = []
    seen_keys: set[str] = set()

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table:
                    continue

                header = [normalize_header(col) for col in table[0]]
                has_dcb = any("denominacao comum" in col for col in header)
                has_concentration = any("concentracao" in col for col in header)
                has_form = any("forma farmaceutica" in col for col in header)
                has_atc = any("codigo atc" in col for col in header)
                if not (has_dcb and has_concentration and has_form and has_atc):
                    continue

                dcb_idx = next(
                    idx for idx, col in enumerate(header) if "denominacao comum" in col
                )
                atc_idx = next(idx for idx, col in enumerate(header) if "codigo atc" in col)

                for row in table[1:]:
                    if dcb_idx >= len(row) or atc_idx >= len(row):
                        continue

                    raw_name = row[dcb_idx]
                    raw_atc = row[atc_idx] or ""
                    if not raw_name:
                        continue

                    atc_code = normalize_space(raw_atc).upper()
                    if not ATC_CODE_RE.match(atc_code):
                        continue

                    name = sanitize_dcb_name(raw_name)
                    if not name:
                        continue

                    key = normalize_key(name)
                    if key in seen_keys:
                        continue

                    seen_keys.add(key)
                    names.append(name)

    return names


def load_existing_entries(catalog_path: Path) -> list[CatalogEntry]:
    src_dir = catalog_path.parents[2]
    sys.path.insert(0, str(src_dir))
    try:
        spec = importlib.util.spec_from_file_location("_medication_catalog_source", catalog_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Nao foi possivel carregar: {catalog_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)

    medications = getattr(module, "MEDICATION_LIST", None)
    if medications is None:
        raise RuntimeError("MEDICATION_LIST nao encontrado em medication_catalog.py")

    return [
        CatalogEntry(
            code=med.code,
            label=ascii_fold(med.label),
            active_ingredient=ascii_fold(med.active_ingredient),
            source_tags=list(med.source_tags),
        )
        for med in medications
    ]


def merge_entries(
    existing_entries: list[CatalogEntry],
    extracted_names: list[str],
) -> tuple[list[CatalogEntry], int]:
    merged = [
        CatalogEntry(
            code=entry.code,
            label=entry.label,
            active_ingredient=entry.active_ingredient,
            source_tags=list(dict.fromkeys(entry.source_tags)),
        )
        for entry in existing_entries
    ]

    used_codes = {entry.code for entry in merged}
    by_key: dict[str, CatalogEntry] = {}
    for entry in merged:
        by_key[normalize_key(entry.label)] = entry
        by_key[normalize_key(entry.active_ingredient)] = entry

    added = 0
    for raw_name in extracted_names:
        label = sanitize_dcb_name(raw_name)
        if not label:
            continue

        key = normalize_key(label)
        match = by_key.get(key)
        if match is not None:
            ensure_rename_tag(match)
            continue

        new_entry = CatalogEntry(
            code=generate_code(label, used_codes),
            label=label,
            active_ingredient=label,
            source_tags=[RENAME_TAG],
        )
        merged.append(new_entry)
        by_key[key] = new_entry
        added += 1

    return merged, added


def py_string(text: str) -> str:
    return json.dumps(text, ensure_ascii=True)


def render_catalog(entries: list[CatalogEntry]) -> str:
    sorted_entries = sorted(entries, key=lambda entry: entry.label.lower())
    lines = [
        '"""In-memory medication catalog for form autocomplete."""',
        "",
        "from __future__ import annotations",
        "",
        "from assistente_medico_api.schemas.medications import MedicationOption",
        "",
        "",
        "def _entry(",
        "    code: str,",
        "    label: str,",
        "    active_ingredient: str,",
        "    source_tags: list[str],",
        ") -> MedicationOption:",
        "    return MedicationOption(",
        "        code=code,",
        "        label=label,",
        "        activeIngredient=active_ingredient,",
        "        sourceTags=source_tags,",
        "    )",
        "",
        "",
        "_MEDICATIONS: list[MedicationOption] = [",
    ]

    for entry in sorted_entries:
        tags = ", ".join(py_string(tag) for tag in sorted(set(entry.source_tags)))
        lines.append(
            "    _entry("
            f"{py_string(entry.code)}, "
            f"{py_string(entry.label)}, "
            f"{py_string(entry.active_ingredient)}, "
            f"[{tags}]"
            "),"
        )

    lines.extend(
        [
            "]",
            "",
            "MEDICATION_LIST: list[MedicationOption] = sorted(",
            "    _MEDICATIONS,",
            "    key=lambda med: med.label.lower(),",
            ")",
            "",
            "",
            "def list_medications() -> list[MedicationOption]:",
            "    return MEDICATION_LIST",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    pdf_path = Path(args.pdf)
    catalog_path = Path(args.catalog)

    if not pdf_path.exists():
        raise SystemExit(f"PDF nao encontrado: {pdf_path}")
    if not catalog_path.exists():
        raise SystemExit(f"Catalogo nao encontrado: {catalog_path}")

    extracted_names = extract_dcb_names(pdf_path)
    existing_entries = load_existing_entries(catalog_path)
    merged_entries, added_count = merge_entries(existing_entries, extracted_names)

    catalog_content = render_catalog(merged_entries)
    catalog_path.write_text(catalog_content, encoding="utf-8")

    print(f"Nomes DCB extraidos: {len(extracted_names)}")
    print(f"Novos itens adicionados: {added_count}")
    print(f"Total no catalogo: {len(merged_entries)}")
    print(f"Arquivo atualizado: {catalog_path}")


if __name__ == "__main__":
    main()
