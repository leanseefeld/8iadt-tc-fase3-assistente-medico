"""Alert endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from assistente_medico_api.deps import get_session
from assistente_medico_api.repositories import alert_repo
from assistente_medico_api.schemas.alerts import (
    AlertCreateRequest,
    AlertListResponse,
    AlertPatchRequest,
    AlertResponse,
)
from assistente_medico_api.services import alert_service

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    patient_id: str | None = None,
    resolved: bool | None = None,
    severity: str | None = None,
    team: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> AlertListResponse:
    """List all alerts with optional filtering."""
    alerts = await alert_repo.list_alerts(
        session,
        patient_id=patient_id,
        resolved=resolved,
        severity=severity,
        team=team,
    )
    payload = [await alert_service.build_alert_schema(a) for a in alerts]
    return AlertListResponse(alerts=payload)


@router.post("/alerts", response_model=AlertResponse, status_code=201)
async def create_alert(
    body: AlertCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> AlertResponse:
    """Create a new alert."""
    alert = await alert_service.create_alert(
        session,
        body.patient_id,
        severity=body.severity,
        category=body.category,
        message=body.message,
        team=body.team,
    )
    await session.commit()
    return AlertResponse(alert=await alert_service.build_alert_schema(alert))


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: str,
    session: AsyncSession = Depends(get_session),
) -> AlertResponse:
    """Get a specific alert by ID."""
    alert = await alert_repo.get_alert_by_id(session, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alerta não encontrado")
    return AlertResponse(alert=await alert_service.build_alert_schema(alert))


@router.patch("/alerts/{alert_id}", response_model=AlertResponse)
async def patch_alert(
    alert_id: str,
    body: AlertPatchRequest,
    session: AsyncSession = Depends(get_session),
) -> AlertResponse:
    """Update an alert (e.g., mark as resolved)."""
    alert = await alert_repo.get_alert_by_id(session, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alerta não encontrado")

    if body.resolved is not None:
        alert.resolved = body.resolved

    await alert_repo.update_alert(session, alert)
    await session.commit()
    return AlertResponse(alert=await alert_service.build_alert_schema(alert))
