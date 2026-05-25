"""Alert business logic and generation."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from assistente_medico_api.models.alert import Alert
from assistente_medico_api.repositories import alert_repo, patient_repo
from assistente_medico_api.schemas.alerts import Alert as AlertSchema
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
