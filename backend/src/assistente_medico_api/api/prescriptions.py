"""Endpoints de prescrições (RCE — protótipo)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from assistente_medico_api.deps import get_session
from assistente_medico_api.repositories import patient_repo, prescription_repo
from assistente_medico_api.schemas.prescriptions import (
    PrescriptionArchiveRequest,
    PrescriptionCreateRequest,
    PrescriptionListResponse,
    SinglePrescriptionResponse,
)
from assistente_medico_api.services import prescription_service

router = APIRouter(tags=["prescriptions"])


@router.get(
    "/patients/{patient_id}/prescriptions",
    response_model=PrescriptionListResponse,
)
async def list_prescriptions_for_patient(
    patient_id: str,
    include_archived: bool = Query(default=False, alias="includeArchived"),
    session: AsyncSession = Depends(get_session),
) -> PrescriptionListResponse:
    patient = await patient_repo.get_patient_by_id(session, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    rows = await prescription_repo.list_by_patient_id(
        session,
        patient_id=patient_id,
        include_archived=include_archived,
    )
    return PrescriptionListResponse(
        prescriptions=[prescription_service.prescription_to_response(r) for r in rows],
    )


@router.post(
    "/patients/{patient_id}/prescriptions",
    response_model=SinglePrescriptionResponse,
    status_code=201,
)
async def create_prescription(
    patient_id: str,
    body: PrescriptionCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> SinglePrescriptionResponse:
    try:
        created = await prescription_service.create_prescription(
            session,
            patient_id=patient_id,
            request=body,
        )
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    return SinglePrescriptionResponse(prescription=created)


@router.get("/prescriptions/{prescription_id}", response_model=SinglePrescriptionResponse)
async def get_prescription(
    prescription_id: str,
    session: AsyncSession = Depends(get_session),
) -> SinglePrescriptionResponse:
    row = await prescription_repo.get_prescription_by_id(session, prescription_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Prescrição não encontrada")
    return SinglePrescriptionResponse(prescription=prescription_service.prescription_to_response(row))


@router.patch(
    "/prescriptions/{prescription_id}/archive",
    response_model=SinglePrescriptionResponse,
)
async def archive_prescription(
    prescription_id: str,
    body: PrescriptionArchiveRequest,
    session: AsyncSession = Depends(get_session),
) -> SinglePrescriptionResponse:
    try:
        updated = await prescription_service.archive_prescription(
            session,
            prescription_id=prescription_id,
            body=body,
        )
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    return SinglePrescriptionResponse(prescription=updated)
