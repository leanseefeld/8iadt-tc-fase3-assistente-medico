"""
Anonimização e contagem de tokens para exportação SFT de conversas.

Usado por llm/fine-tuning/export-positive-conversations.ipynb.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

PCDT_MARKER = "Resultado da busca por trechos PCDT:"
PCDT_NEXT_SECTION = "Mensagem do médico:"

# Rótulos de comorbidades (espelho de patient_context._COMORBIDITY_LABELS).
_COMORBIDITY_LABELS: dict[str, str] = {
    "HAS": "Hipertensão Arterial Sistêmica",
    "DM2": "Diabetes Mellitus Tipo 2",
    "DM1": "Diabetes Mellitus Tipo 1",
    "IRC": "Insuficiência Renal Crônica",
    "DRC-Dialise": "Doença Renal Crônica em Diálise",
    "IC": "Insuficiência Cardíaca",
    "DAC": "Doença Arterial Coronariana",
    "AVC-Previo": "Acidente Vascular Cerebral Prévio",
    "FAi": "Fibrilação Atrial",
    "Asma": "Asma",
    "DPOC": "Doença Pulmonar Obstrutiva Crônica",
    "Obesidade": "Obesidade",
    "Hepatopatia": "Doença Hepática Crônica",
    "Autoimune": "Doença Autoimune",
    "Imunossuprimido": "Imunossupressão",
    "HIV": "HIV",
    "Cancer": "Câncer Ativo",
    "Tabagismo": "Tabagismo",
    "Etilismo": "Etilismo Crônico",
    "Gravidez": "Gravidez",
    "Puerperio (resguardo)": "Puerpério",
    "Outras": "Outras Comorbidades",
}

_STATIC_ALLOWLIST = frozenset(
    {
        "PCDT",
        "Contexto",
        "clínico",
        "Resultado",
        "busca",
        "trechos",
        "Mensagem",
        "médico",
        "médica",
    }
)

PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("CPF", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("PHONE", re.compile(r"(\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4})")),
    ("EMAIL", re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")),
    ("CEP", re.compile(r"\b\d{5}-?\d{3}\b")),
]

_DDD_POOL = (11, 21, 31, 41, 51, 61, 71, 81, 85)


def pseudonymize_id(raw_id: str, prefix: str, salt: str) -> str:
    """Gera pseudônimo estável com prefixo de tipo."""
    digest = hashlib.sha256(f"{salt}:{raw_id}".encode()).hexdigest()[:12]
    return f"{prefix}_{digest}"


def assign_fake_name(patient_id: str, salt: str) -> str:
    """Nome brasileiro sintético estável por paciente."""
    from faker import Faker

    seed = int(hashlib.sha256(f"{salt}:name:{patient_id}".encode()).hexdigest()[:8], 16)
    faker = Faker("pt_BR")
    faker.seed_instance(seed)
    return faker.name()


def extract_pcdt_spans(text: str) -> list[tuple[int, int]]:
    """Localiza blocos PCDT (marcador inclusive até a próxima seção ou fim)."""
    spans: list[tuple[int, int]] = []
    if not text or PCDT_MARKER not in text:
        return spans
    start = 0
    while True:
        idx = text.find(PCDT_MARKER, start)
        if idx < 0:
            break
        # Protege desde o marcador (inclusive) até o cabeçalho da próxima seção.
        region_start = idx
        next_idx = text.find(PCDT_NEXT_SECTION, idx + len(PCDT_MARKER))
        region_end = next_idx if next_idx >= 0 else len(text)
        spans.append((region_start, region_end))
        start = region_end
    return spans


def pcdt_allowlist_tokens(text: str, spans: list[tuple[int, int]]) -> set[str]:
    """Tokens únicos (len >= 3) extraídos dos spans PCDT."""
    tokens: set[str] = set()
    for start, end in spans:
        chunk = text[start:end]
        for word in re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9\-]{2,}", chunk):
            tokens.add(word)
    return tokens


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not spans:
        return []
    ordered = sorted(spans)
    merged: list[tuple[int, int]] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _editable_slices(text: str, protected: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Partes do texto fora dos spans protegidos."""
    if not text:
        return []
    if not protected:
        return [(0, len(text))]
    protected = _merge_spans(protected)
    slices: list[tuple[int, int]] = []
    pos = 0
    for start, end in protected:
        if pos < start:
            slices.append((pos, start))
        pos = max(pos, end)
    if pos < len(text):
        slices.append((pos, len(text)))
    return slices


def _token_overlaps_allowlist(token: str, allow_list: set[str]) -> bool:
    low = token.lower()
    for item in allow_list:
        if low == item.lower() or low in item.lower() or item.lower() in low:
            return True
    return False


def _cpf_check_digits(nine: list[int]) -> list[int]:
    """Calcula os dois dígitos verificadores de um CPF (9 primeiros dígitos)."""
    s1 = sum(d * w for d, w in zip(nine, range(10, 1, -1)))
    d1 = (s1 * 10) % 11
    d1 = 0 if d1 == 10 else d1
    s2 = sum(d * w for d, w in zip(nine + [d1], range(11, 1, -1)))
    d2 = (s2 * 10) % 11
    d2 = 0 if d2 == 10 else d2
    return [d1, d2]


def _synthetic_cpf(seed_hex: str) -> str:
    base = int(seed_hex[:16], 16) % 900_000_000 + 100_000_000
    nine = [int(c) for c in f"{base:09d}"]
    d1, d2 = _cpf_check_digits(nine)
    digits = nine + [d1, d2]
    return (
        f"{digits[0]}{digits[1]}{digits[2]}."
        f"{digits[3]}{digits[4]}{digits[5]}."
        f"{digits[6]}{digits[7]}{digits[8]}-"
        f"{digits[9]}{digits[10]}"
    )


def _synthetic_phone(seed_hex: str) -> str:
    n = int(seed_hex[:12], 16)
    ddd = _DDD_POOL[n % len(_DDD_POOL)]
    part = 900000000 + (n % 99_999_999)
    s = f"{part:09d}"
    return f"({ddd}) {s[0]}{s[1]}{s[2]}{s[3]}{s[4]}-{s[5:]}{s[6]}{s[7]}{s[8]}"


def _synthetic_email(seed_hex: str) -> str:
    n = int(seed_hex[:8], 16) % 1_000_000
    return f"usuario{n}@exemplo.com.br"


def _synthetic_cep(seed_hex: str) -> str:
    n = int(seed_hex[:10], 16) % 100_000_000
    s = f"{n:08d}"
    return f"{s[:5]}-{s[5:]}"


class ReplacementRegistry:
    """Mapeia (entity_type, valor_original) → valor sintético estável por salt."""

    def __init__(self, salt: str) -> None:
        self._salt = salt
        self._cache: dict[tuple[str, str], str] = {}
        self.counts: dict[str, int] = {}

    def _canonical(self, original: str) -> str:
        return original.strip()

    def replace(self, entity_type: str, original: str) -> str:
        key = (entity_type, self._canonical(original))
        if key in self._cache:
            return self._cache[key]
        seed = hashlib.sha256(
            f"{self._salt}:{entity_type}:{key[1]}".encode()
        ).hexdigest()
        if entity_type == "CPF":
            value = _synthetic_cpf(seed)
        elif entity_type == "PHONE":
            value = _synthetic_phone(seed)
        elif entity_type == "EMAIL":
            value = _synthetic_email(seed)
        elif entity_type == "CEP":
            value = _synthetic_cep(seed)
        else:
            value = original
        self._cache[key] = value
        self.counts[entity_type] = self.counts.get(entity_type, 0) + 1
        return value


def build_clinical_allow_list(
    *,
    pcdt_texts: Iterable[str],
    patient_names: Iterable[str],
    fake_names: Iterable[str],
    cid_labels: Iterable[str],
) -> set[str]:
    """Monta allow-list clínica para evitar regex em termos médicos."""
    allow: set[str] = set(_STATIC_ALLOWLIST)
    allow.update(_COMORBIDITY_LABELS.values())
    for text in pcdt_texts:
        for start, end in extract_pcdt_spans(text):
            allow.update(pcdt_allowlist_tokens(text, [(start, end)]))
    for name in list(patient_names) + list(fake_names):
        n = (name or "").strip()
        if len(n) >= 3:
            allow.add(n)
            for part in n.split():
                if len(part) >= 3:
                    allow.add(part)
    for label in cid_labels:
        lbl = (label or "").strip()
        if len(lbl) >= 3:
            allow.add(lbl)
            for part in re.findall(r"[A-Za-zÀ-ÿ]{3,}", lbl):
                allow.add(part)
    return allow


def _apply_layer1_in_slice(
    slice_text: str,
    *,
    patient_name: str | None,
    fake_name: str | None,
    replace_first_token: bool,
) -> str:
    if not slice_text:
        return slice_text
    out = slice_text
    if patient_name and fake_name and len(patient_name) >= 3:
        pattern = re.compile(re.escape(patient_name), re.IGNORECASE)
        out = pattern.sub(fake_name, out)
        out = re.sub(
            r"(-\s*Nome:\s*).+",
            rf"\1{fake_name}",
            out,
            flags=re.IGNORECASE,
        )
        if replace_first_token:
            first = patient_name.split()[0]
            if len(first) >= 3:
                out = re.sub(
                    rf"\b{re.escape(first)}\b",
                    fake_name.split()[0],
                    out,
                    flags=re.IGNORECASE,
                )
    return out


def _apply_layer2_in_slice(
    slice_text: str,
    *,
    registry: ReplacementRegistry,
    allow_list: set[str],
) -> str:
    if not slice_text:
        return slice_text

    def _sub_entity(match: re.Match[str], entity_type: str) -> str:
        original = match.group(0)
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9\-]+", original):
            if _token_overlaps_allowlist(token, allow_list):
                return original
        return registry.replace(entity_type, original)

    out = slice_text
    for entity_type, pattern in PII_PATTERNS:
        out = pattern.sub(lambda m, et=entity_type: _sub_entity(m, et), out)
    return out


def _anonymize_editable_slice(
    slice_text: str,
    *,
    registry: ReplacementRegistry,
    allow_list: set[str],
    patient_name: str | None,
    fake_name: str | None,
    replace_first_token: bool,
) -> str:
    slice_text = _apply_layer1_in_slice(
        slice_text,
        patient_name=patient_name,
        fake_name=fake_name,
        replace_first_token=replace_first_token,
    )
    return _apply_layer2_in_slice(
        slice_text,
        registry=registry,
        allow_list=allow_list,
    )


def anonymize_text(
    text: str,
    *,
    registry: ReplacementRegistry,
    allow_list: set[str],
    patient_name: str | None,
    fake_name: str | None,
    replace_first_token: bool = False,
) -> tuple[str, list[tuple[int, int]]]:
    """Anonimiza uma string preservando spans PCDT byte-a-byte."""
    if not text:
        return text, []
    pcdt_spans = _merge_spans(extract_pcdt_spans(text))
    if not pcdt_spans:
        return (
            _anonymize_editable_slice(
                text,
                registry=registry,
                allow_list=allow_list,
                patient_name=patient_name,
                fake_name=fake_name,
                replace_first_token=replace_first_token,
            ),
            [],
        )

    parts: list[str] = []
    pos = 0
    for start, end in pcdt_spans:
        if pos < start:
            parts.append(
                _anonymize_editable_slice(
                    text[pos:start],
                    registry=registry,
                    allow_list=allow_list,
                    patient_name=patient_name,
                    fake_name=fake_name,
                    replace_first_token=replace_first_token,
                )
            )
        parts.append(text[start:end])
        pos = end
    if pos < len(text):
        parts.append(
            _anonymize_editable_slice(
                text[pos:],
                registry=registry,
                allow_list=allow_list,
                patient_name=patient_name,
                fake_name=fake_name,
                replace_first_token=replace_first_token,
            )
        )
    return "".join(parts), pcdt_spans


def anonymize_sft_text(
    llm_input: list[dict[str, Any]],
    llm_output: str,
    *,
    registry: ReplacementRegistry,
    fake_names: dict[str, str],
    allow_list: set[str],
    patient_id: str,
    patient_name: str | None,
    replace_first_token: bool = False,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """
    Anonimiza llm_input (lista role/content) e llm_output.

    Retorna (llm_input_anon, llm_output_anon, meta) com spans PCDT para validação.
    """
    fake_name = fake_names.get(patient_id)
    new_input: list[dict[str, Any]] = []
    all_pcdt_spans: list[tuple[str, list[tuple[int, int]]]] = []

    for msg in llm_input or []:
        role = msg.get("role", "")
        content = msg.get("content") or ""
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        anon_content, spans = anonymize_text(
            str(content),
            registry=registry,
            allow_list=allow_list,
            patient_name=patient_name,
            fake_name=fake_name,
            replace_first_token=replace_first_token,
        )
        if spans:
            all_pcdt_spans.append(("input", spans))
        new_input.append({**msg, "role": role, "content": anon_content})

    anon_output, out_spans = anonymize_text(
        llm_output or "",
        registry=registry,
        allow_list=allow_list,
        patient_name=patient_name,
        fake_name=fake_name,
        replace_first_token=replace_first_token,
    )
    if out_spans:
        all_pcdt_spans.append(("output", out_spans))

    meta = {"pcdt_span_refs": all_pcdt_spans}
    return new_input, anon_output, meta


def validate_anonymization(
    *,
    llm_input: list[dict[str, Any]],
    llm_output: str,
    original_llm_input: list[dict[str, Any]],
    original_llm_output: str,
    patient_name: str | None,
    fake_name: str | None,
) -> tuple[bool, list[str]]:
    """Validações pós-anonimização; retorna (ok, erros)."""
    errors: list[str] = []
    combined_out = llm_output + "".join(
        (m.get("content") or "") for m in llm_input
    )
    if patient_name and len(patient_name) >= 3:
        if patient_name.lower() in combined_out.lower():
            errors.append("raw_patient_name_leaked")

    def _check_pcdt_unchanged(original: str, anonymized: str) -> None:
        orig_spans = extract_pcdt_spans(original)
        anon_spans = extract_pcdt_spans(anonymized)
        if len(orig_spans) != len(anon_spans):
            errors.append("pcdt_span_modified")
            return
        for (os, oe), (as_, ae) in zip(orig_spans, anon_spans):
            if original[os:oe] != anonymized[as_:ae]:
                errors.append("pcdt_span_modified")

    for orig, anon in zip(original_llm_input, llm_input):
        _check_pcdt_unchanged(
            str(orig.get("content") or ""),
            str(anon.get("content") or ""),
        )

    _check_pcdt_unchanged(original_llm_output or "", llm_output or "")

    if fake_name and "- Nome:" in combined_out:
        if fake_name not in combined_out:
            errors.append("fake_name_not_in_nome_line")

    return len(errors) == 0, errors


def count_sft_tokens(
    llm_input: list[dict[str, Any]],
    llm_output: str,
    tokenizer: Any,
) -> int:
    """Conta tokens Llama no par input+output via chat template."""
    messages = list(llm_input or []) + [
        {"role": "assistant", "content": llm_output or ""}
    ]
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )
    return len(tokenizer.encode(text, add_special_tokens=False))


@dataclass
class ExportFunnel:
    """Contadores do funil de exportação."""

    scanned: int = 0
    exported: int = 0
    dropped: dict[str, int] = field(default_factory=dict)

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1
