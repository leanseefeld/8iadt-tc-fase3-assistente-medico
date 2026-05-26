"""Orquestração do grafo multi-nó de alertas clínicos com PCDT/RAG."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.clinical_alerts import seed_run_state
from assistente_medico_api.models.exam import Exam
from assistente_medico_api.models.patient import Patient, VitalSigns
from assistente_medico_api.observability.clinical_audit_jsonl import (
    ClinicalAuditAction,
    clinical_audit,
)
from assistente_medico_api.services import alert_service

_LOGGER = logging.getLogger("assistente_medico.clinical_alerts")


def patient_core_bundle(patient: Patient) -> dict[str, Any]:
    """Paciente persistente como dicionário leve para o grafo."""
    return {
        "name": patient.name,
        "age": patient.age,
        "sex": patient.sex,
        "gender": patient.gender,
        "symptoms": patient.symptoms or "",
        "comorbidities": list(patient.comorbidities or []),
        "current_medications": list(patient.current_medications or []),
        "cid_code": patient.cid_code or "",
        "cid_label": patient.cid_label or "",
    }


def vital_sign_row_to_alert_dict(row: VitalSigns) -> dict[str, Any]:
    """Últimos sinais vitais consolidados."""
    return {
        "blood_pressure": row.blood_pressure,
        "temperature": float(row.temperature),
        "oxygen_saturation": int(row.oxygen_saturation),
        "heart_rate": int(row.heart_rate),
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
    }


def exam_to_focus(exam: Exam) -> dict[str, Any]:
    """Recorte necessário sobre o exame no gatilho de resultado."""
    return {
        "id": exam.id,
        "name": exam.name,
        "status": exam.status,
        "result": exam.result or "",
        "interpretation": exam.interpretation or "",
        "completed_at": exam.completed_at.isoformat() if exam.completed_at else None,
    }


async def evaluate_clinical_alerts(
    graph: Any | None,
    settings: Settings,
    session: AsyncSession,
    *,
    patient_id: str,
    trigger_type: str,
    patient: Patient | None,
    exam_focus: dict[str, Any] | None = None,
    latest_vitals: dict[str, Any] | None = None,
) -> None:
    """
    Executa o fluxo LangGraph e persiste alertas respeitando deduplicação.

    `patient` já carregado evita segundo SELECT quando o chamador já o possui.
    """
    if graph is None:
        _LOGGER.warning("clinical_alert_graph indisponível — ignorando avaliação de alertas")
        return

    row = patient
    if row is None:
        from assistente_medico_api.repositories import patient_repo

        row = await patient_repo.get_patient_by_id(session, patient_id)
    if row is None:
        return

    bundle = patient_core_bundle(row)
    seed = seed_run_state(
        patient_id=patient_id,
        trigger_type=trigger_type,
        patient_bundle=bundle,
        exam_focus=exam_focus,
        latest_vitals=latest_vitals,
    )

    cfg = {"tags": ["clinical_alerts"], "metadata": {"patient_id": patient_id}}
    final = await graph.ainvoke(seed, cfg)

    payloads = final.get("alert_payloads") or []
    trace = final.get("audit_trace") or {}
    steps = final.get("reasoning_steps") or []

    created = 0
    skipped = 0
    for payload in payloads:
        dedupe_key = payload.get("dedupe_key") or ""
        dup = dedupe_key and await alert_service.would_duplicate_unresolved_alert(
            session,
            patient_id,
            dedupe_key=dedupe_key,
        )
        if dup:
            skipped += 1
            continue
        await alert_service.create_alert(
            session,
            patient_id,
            severity=str(payload.get("severity") or "info"),
            category=str(payload.get("category") or "clinical"),
            message=str(payload.get("message") or "").strip(),
            team=str(payload.get("team") or "all"),
            dedupe_key=dedupe_key or None,
        )
        created += 1

    clinical_audit(
        ClinicalAuditAction.AVALIACAO_ALERTA_CLINICO_PCDT,
        patient_id=patient_id,
        patient_name=row.name,
        descricao=(
            f"Avaliação multi-nó de alertas ({trigger_type}): emitidos={created}, "
            f"pulados_deduplicacao={skipped}."
        ),
        detalhes={
            "trigger": trigger_type,
            "run_id": seed.get("run_id"),
            "racino_passos_resumo": steps[-8:],  # evita payloads enormes em JSONL
            "audit_trace_compacto": {
                "sources_reference": (trace.get("sources_reference") or [])[:12],
                "sources_patient_context": (trace.get("sources_patient_context") or [])[:12],
                "merged_context_chars": trace.get("merged_context_chars"),
            },
            "payloads_previstos": len(payloads),
        },
        settings=settings,
    )
