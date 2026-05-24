"""Alert business logic and generation."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from assistente_medico_api.models.alert import Alert
from assistente_medico_api.models.exam import Exam
from assistente_medico_api.models.patient import Patient
from assistente_medico_api.repositories import alert_repo, patient_repo
from assistente_medico_api.schemas.alerts import Alert as AlertSchema, AlertCreateRequest
from assistente_medico_api.observability.audit import truncate
from assistente_medico_api.observability.clinical_audit_jsonl import ClinicalAuditAction, clinical_audit

def _new_alert_id() -> str:
    return f"alert-{uuid4()}"


async def create_alert(
    session: AsyncSession,
    patient_id: str,
    *,
    severity: str = "info",
    category: str = "clinical",
    message: str,
    team: str = "all",
) -> Alert:
    """Create and persist an alert."""
    alert = Alert(
        id=_new_alert_id(),
        patient_id=patient_id,
        severity=severity,
        category=category,
        message=message,
        team=team,
        resolved=False,
    )
    created = await alert_repo.create_alert(session, alert)
    pname = None
    row = await patient_repo.get_patient_by_id(session, patient_id)
    if row is not None:
        pname = row.name

    clinical_audit(
        ClinicalAuditAction.ALERTA_EMITIDO,
        patient_id=patient_id,
        patient_name=pname,
        descricao=f"Alerta {created.id} ({severity}/{category}): {truncate(message)}",
        detalhes={
            "alert_id": created.id,
            "severidade": severity,
            "categoria": category,
            "equipe": team,
        },
    )
    return created

async def generate_alerts_for_patient(
    session: AsyncSession,
    patient: Patient,
    exams: list[Exam],
) -> list[Alert]:
    """
    Generate alerts based on patient status and exams.

    Rules:
    - If patient has critical exams pending (status='pending') → critical exam alert
    - If patient has multiple pending exams → moderate alert
    - If oxygen saturation is low (detected from vitals) → critical alert
    """
    alerts: list[Alert] = []

    # Check for pending exams
    pending_exams = [e for e in exams if e.status == "pending"]

    if len(pending_exams) > 3:
        # Multiple pending exams → moderate alert
        alert = await create_alert(
            session,
            patient.id,
            severity="critical",
            category="exam",
            message=f"Paciente {patient.name} possui {len(pending_exams)} exames pendentes que requerem atenção imediata.",
            team="doctors",
        )
        alerts.append(alert)
    elif len(pending_exams) > 0:
        # Some pending exams → moderate alert
        exam_names = ", ".join(e.name for e in pending_exams[:3])
        alert = await create_alert(
            session,
            patient.id,
            severity="moderate",
            category="exam",
            message=f"Exames aguardando revisão: {exam_names}.",
            team="doctors",
        )
        alerts.append(alert)

    # Check for certain critical exam types
    critical_exam_types = ["PCR", "Hemograma", "Lactato"]
    critical_exams = [e for e in exams if any(t in e.name for t in critical_exam_types) and e.status == "pending"]
    if critical_exams:
        alert = await create_alert(
            session,
            patient.id,
            severity="critical",
            category="exam",
            message=f"Exame crítico pendente: {critical_exams[0].name}. Revisão urgente solicitada.",
            team="doctors",
        )
        alerts.append(alert)

    return alerts


async def build_alert_schema(alert: Alert) -> AlertSchema:
    """Convert Alert model to schema with camelCase."""
    return AlertSchema(
        id=alert.id,
        patientId=alert.patient_id,
        severity=alert.severity,
        category=alert.category,
        message=alert.message,
        team=alert.team,
        createdAt=alert.created_at,
        resolved=alert.resolved,
    )
