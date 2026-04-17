"""Medication catalog endpoint."""

from fastapi import APIRouter

from assistente_medico_api.schemas.medications import MedicationListResponse
from assistente_medico_api.services.medication_catalog import list_medications

router = APIRouter(tags=["patients"])


@router.get("/medications", response_model=MedicationListResponse)
async def get_medications() -> MedicationListResponse:
    return MedicationListResponse(medications=list_medications())
