"""Nó de contexto clínico do paciente admitido + formatação para o prompt."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from assistente_medico_api.config import Settings
from assistente_medico_api.db.session import AsyncSessionLocal
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.models.exam import Exam
from assistente_medico_api.models.patient import Patient
from assistente_medico_api.observability.audit import audit
from assistente_medico_api.repositories import patient_repo

# Rótulos de identidade de gênero (códigos canônicos do check-in).
_GENDER_LABELS: dict[str, str] = {
    "mulher_cis": "Mulher cisgênero",
    "homem_cis": "Homem cisgênero",
    "mulher_trans": "Mulher transgênero",
    "homem_trans": "Homem transgênero",
    "travesti": "Travesti",
    "nao_binario": "Não binário",
    "outro": "Outro",
}

# Cópia do catálogo de comorbidities.py para lookup de labels no prompt.
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

_EXAM_LOOKBACK = timedelta(days=183)  # ~6 meses
_COMPLETED_STATUSES = frozenset({"completed", "critical"})


def format_sex_label(sex: str) -> str:
    """Mapeia sexo biológico M/F para rótulo pt-BR."""
    normalized = (sex or "").strip().upper()
    if normalized == "F":
        return "Feminino"
    if normalized == "M":
        return "Masculino"
    return sex or "Não informado"


def format_gender_label(code: str | None) -> str | None:
    """Resolve código de identidade de gênero; desconhecido retorna o código bruto."""
    if not code:
        return None
    return _GENDER_LABELS.get(code.strip(), code.strip())


def resolve_comorbidity_labels(codes: list[str]) -> list[str]:
    """Resolve códigos de comorbidade para labels legíveis ao LLM."""
    labels: list[str] = []
    for code in codes:
        text = (code or "").strip()
        if not text:
            continue
        labels.append(_COMORBIDITY_LABELS.get(text, text))
    return labels


def format_symptoms_block(symptoms: str) -> str:
    """Formata sintomas multilinha com prefixo de lista."""
    lines = [line.strip() for line in (symptoms or "").splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(f"  - {line}" for line in lines)


def format_date_pt_br(dt: datetime) -> str:
    """Formata data no padrão dd/mm/aaaa."""
    return dt.strftime("%d/%m/%Y")


def format_relative_time(dt: datetime, reference: datetime) -> str:
    """Retorna texto relativo em pt-BR (dias, horas ou minutos)."""
    ref = reference if reference.tzinfo else reference.replace(tzinfo=UTC)
    target = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    delta = ref - target
    if delta.total_seconds() < 0:
        return "há menos de 1 minuto"

    days = delta.days
    if days >= 1:
        suffix = "dia" if days == 1 else "dias"
        return f"há {days} {suffix}"

    hours = int(delta.total_seconds() // 3600)
    if hours >= 1:
        suffix = "hora" if hours == 1 else "horas"
        return f"há {hours} {suffix}"

    minutes = int(delta.total_seconds() // 60)
    if minutes >= 1:
        suffix = "minuto" if minutes == 1 else "minutos"
        return f"há {minutes} {suffix}"

    return "há menos de 1 minuto"


def _exam_requested_at(exam: Exam) -> datetime:
    return exam.requested_at if exam.requested_at.tzinfo else exam.requested_at.replace(tzinfo=UTC)


def _format_exam_line(exam: Exam, *, reference: datetime, pending: bool) -> str:
    if pending:
        requested = _exam_requested_at(exam)
        return (
            f"- {exam.name}: pendente "
            f"(solicitado em {format_date_pt_br(requested)}, "
            f"{format_relative_time(requested, reference)})"
        )

    result = (exam.result or "").strip() or "sem resultado"
    if exam.completed_at:
        completed = exam.completed_at if exam.completed_at.tzinfo else exam.completed_at.replace(tzinfo=UTC)
        return (
            f"- {exam.name}: {result} "
            f"(concluído em {format_date_pt_br(completed)}, "
            f"{format_relative_time(completed, reference)})"
        )
    return f"- {exam.name}: {result} (concluído em data não registrada)"


def format_exam_sections(
    exams: list[Exam],
    *,
    cutoff: datetime,
    reference: datetime | None = None,
) -> tuple[str, str]:
    """Separa exames pendentes e concluídos dos últimos 6 meses (ASC por requested_at)."""
    ref = reference or datetime.now(UTC)
    cutoff_dt = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=UTC)

    recent = [exam for exam in exams if _exam_requested_at(exam) >= cutoff_dt]
    pending = sorted(
        [exam for exam in recent if exam.status == "pending"],
        key=_exam_requested_at,
    )
    completed = sorted(
        [exam for exam in recent if exam.status in _COMPLETED_STATUSES],
        key=_exam_requested_at,
    )

    pending_text = "\n".join(
        _format_exam_line(exam, reference=ref, pending=True) for exam in pending
    )
    completed_text = "\n".join(
        _format_exam_line(exam, reference=ref, pending=False) for exam in completed
    )
    return pending_text, completed_text


def format_patient_context(
    patient: Patient,
    exams: list[Exam],
    *,
    reference: datetime | None = None,
) -> str:
    """Monta bloco de contexto clínico do paciente para o prompt."""
    ref = reference or datetime.now(UTC)
    cutoff = ref - _EXAM_LOOKBACK

    gender_label = format_gender_label(patient.gender)
    symptoms_block = format_symptoms_block(patient.symptoms)
    comorbidity_labels = resolve_comorbidity_labels(patient.comorbidities or [])
    medications = ", ".join(patient.current_medications or []) or "Nenhum"
    pending_exams, completed_exams = format_exam_sections(exams, cutoff=cutoff, reference=ref)

    lines = [
        "Contexto do paciente admitido:",
        f"- Nome: {patient.name}",
        f"- Sexo biológico (nascimento): {format_sex_label(patient.sex)}",
    ]
    if gender_label:
        lines.append(f"- Identidade de gênero: {gender_label}")
    lines.extend(
        [
            f"- Idade: {patient.age} anos",
            f"- Sintomas:\n{symptoms_block}" if symptoms_block else "- Sintomas: Não informado",
            f"- Medicamentos em uso: {medications}",
            f"- CID/diagnóstico: {patient.cid_code} — {patient.cid_label}".strip(" —"),
            f"- Comorbidades: {', '.join(comorbidity_labels) if comorbidity_labels else 'Nenhuma'}",
            "- Exames concluídos (últimos 6 meses):",
            completed_exams or "  Nenhum",
            "- Exames pendentes (últimos 6 meses):",
            pending_exams or "  Nenhum",
        ]
    )
    return "\n".join(lines)


async def load_patient_context_node(state: ChatRAGState, settings: Settings) -> dict:
    """
    Carrega contexto clínico do paciente admitido (cache no checkpoint por thread).

    Cache hit: patient_context já preenchido → retorna {}.
    """
    _ = settings
    pid = (state.get("patient_id") or "").strip()
    existing_steps = list(state.get("reasoning_steps") or [])

    # Cache hit — contexto já carregado neste thread.
    if state.get("patient_context"):
        return {}

    if not pid:
        step = "Contexto clínico: paciente não informado."
        audit("rag_patient_context_loaded", kind="rag", patient_id=None, cache_hit=False, loaded=False)
        return {
            "patient_context": "",
            "reasoning_steps": existing_steps + [step],
        }

    t0 = time.perf_counter()
    async with AsyncSessionLocal() as session:
        patient = await patient_repo.get_patient_by_id(session, pid)
        if patient is None:
            step = f"Contexto clínico: paciente {pid} não encontrado."
            audit(
                "rag_patient_context_loaded",
                kind="rag",
                patient_id=pid,
                cache_hit=False,
                loaded=False,
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            )
            return {
                "patient_context": "",
                "reasoning_steps": existing_steps + [step],
            }

        exams = await patient_repo.list_exams(session, pid)
        formatted = format_patient_context(patient, exams)

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    step = f"Contexto clínico carregado: {patient.name}, {patient.age}a, CID {patient.cid_code}"
    audit(
        "rag_patient_context_loaded",
        kind="rag",
        patient_id=pid,
        cache_hit=False,
        loaded=True,
        exam_count=len(exams),
        latency_ms=latency_ms,
    )
    return {
        "patient_context": formatted,
        "reasoning_steps": existing_steps + [step],
    }
