"""Regras de negócio para prescrições."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from assistente_medico_api.models.prescription import Prescription
from assistente_medico_api.repositories import patient_repo, prescription_repo
from assistente_medico_api.schemas.prescriptions import (
    PrescriptionArchiveRequest,
    PrescriptionCreateRequest,
    PrescriptionItemSchema,
    PrescriptionResponse,
)
from assistente_medico_api.observability.audit import audit, mask_cpf, truncate


def _items_to_db(payload: list[PrescriptionItemSchema]) -> list[dict]:
    out: list[dict] = []
    for it in payload:
        d = it.model_dump(mode="json", by_alias=False)
        out.append(d)
    return out


def _items_from_db(raw: list[dict]) -> list[PrescriptionItemSchema]:
    return [PrescriptionItemSchema.model_validate(x) for x in raw]


def prescription_to_response(row: Prescription) -> PrescriptionResponse:
    items = _items_from_db(row.items or [])
    return PrescriptionResponse(
        id=row.id,
        patient_id=row.patient_id,
        patient_cpf=row.patient_cpf,
        prescriber_kind=row.prescriber_kind,
        prescriber_name=row.prescriber_name,
        prescriber_crm=row.prescriber_crm,
        prescriber_crm_uf=row.prescriber_crm_uf,
        institution_name=row.institution_name,
        institution_cnpj_cnes=row.institution_cnpj_cnes,
        institution_address=row.institution_address,
        institution_phone=row.institution_phone,
        items=items,
        notes=row.notes,
        chat_thread_id=row.chat_thread_id,
        decision_flow_run_id=row.decision_flow_run_id,
        issued_at=row.issued_at,
        archived_at=row.archived_at,
        archived_reason=row.archived_reason,
        archived_by=row.archived_by,
    )


def _validate_create(req: PrescriptionCreateRequest) -> None:
    if req.prescriber_kind not in ("doctor", "ai_assistant"):
        raise HTTPException(
            status_code=400,
            detail="prescriberKind deve ser doctor ou ai_assistant",
        )
    if not req.items:
        raise HTTPException(status_code=400, detail="Inclua ao menos um medicamento")
    if req.prescriber_kind == "doctor":
        if not (req.prescriber_crm or "").strip() or not (req.prescriber_crm_uf or "").strip():
            raise HTTPException(
                status_code=400,
                detail="CRM e UF são obrigatórios quando prescriberKind é doctor",
            )


async def create_prescription(
    session: AsyncSession,
    *,
    patient_id: str,
    request: PrescriptionCreateRequest,
) -> PrescriptionResponse:
    patient = await patient_repo.get_patient_by_id(session, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    _validate_create(request)

    row = Prescription(
        patient_id=patient_id,
        patient_cpf=(request.patient_cpf or "").strip() or None,
        prescriber_kind=request.prescriber_kind,
        prescriber_name=request.prescriber_name.strip(),
        prescriber_crm=(request.prescriber_crm or "").strip() or None,
        prescriber_crm_uf=(request.prescriber_crm_uf or "").strip() or None,
        institution_name=(request.institution_name or "").strip() or None,
        institution_cnpj_cnes=(request.institution_cnpj_cnes or "").strip() or None,
        institution_address=(request.institution_address or "").strip() or None,
        institution_phone=(request.institution_phone or "").strip() or None,
        items=_items_to_db(request.items),
        notes=(request.notes or "").strip() or None,
        chat_thread_id=(request.chat_thread_id or "").strip() or None,
        decision_flow_run_id=(request.decision_flow_run_id or "").strip() or None,
        issued_at=datetime.now(UTC),
    )
    created = await prescription_repo.create_prescription(session, row)
    audit(
        "prescription_created",
        kind="clinical",
        patient_id=patient_id,
        prescription_id=created.id,
        prescriber_kind=created.prescriber_kind,
        prescriber_crm=created.prescriber_crm or "",
        items_count=len(request.items),
        patient_cpf=mask_cpf(created.patient_cpf or request.patient_cpf),
        chat_thread_id=(created.chat_thread_id or ""),
        decision_flow_run_id=(created.decision_flow_run_id or ""),
    )
    return prescription_to_response(created)


async def archive_prescription(
    session: AsyncSession,
    *,
    prescription_id: str,
    body: PrescriptionArchiveRequest,
) -> PrescriptionResponse:
    row = await prescription_repo.get_prescription_by_id(session, prescription_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Prescrição não encontrada")
    if row.archived_at is not None:
        raise HTTPException(status_code=409, detail="Prescrição já arquivada")

    row.archived_at = datetime.now(UTC)
    row.archived_reason = body.reason.strip()
    row.archived_by = body.archived_by.strip()
    await prescription_repo.update_prescription(session, row)

    audit(
        "prescription_archived",
        kind="clinical",
        patient_id=row.patient_id,
        prescription_id=row.id,
        reason=truncate(str(row.archived_reason or "")),
        archived_by=str(row.archived_by or ""),
        prescriber_kind=row.prescriber_kind,
    )
    return prescription_to_response(row)
