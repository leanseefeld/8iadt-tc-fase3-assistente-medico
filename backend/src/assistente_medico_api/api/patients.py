"""Patient and sub-resource endpoints backed by SQLite."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from assistente_medico_api.config import Settings
from assistente_medico_api.deps import get_session
from assistente_medico_api.models.exam import Exam
from assistente_medico_api.models.suggested_item import SuggestedItem
from assistente_medico_api.models.attachment import ExamAttachment
from assistente_medico_api.repositories import exam_repo, patient_repo, suggested_item_repo, attachment_repo
from assistente_medico_api.schemas.exams import ExamCreateRequest, ExamPatchRequest, ExamResponse
from assistente_medico_api.schemas.patients import (
    PatientCreateRequest,
    PatientListResponse,
    PatientPatchRequest,
    PatientResponse,
    VitalSignsHistoryResponse,
    VitalSignsPatchRequest,
)
from assistente_medico_api.schemas.suggested_items import (
    SuggestedItemCreateRequest,
    SuggestedItemPatchRequest,
    SuggestedItemResponse,
)
from assistente_medico_api.services import alert_service, patient_service
from assistente_medico_api.services.patient_context_cache import invalidate_patient_context
from assistente_medico_api.observability.clinical_audit_jsonl import (
    ClinicalAuditAction,
    audit_context_is_demo,
    clinical_audit,
)
from assistente_medico_api.observability.context import set_patient_id

router = APIRouter(tags=["patients"])


def _extract_systolic(value: str | None) -> int | None:
    if not value:
        return None
    left = str(value).split("/")[0].strip()
    if not left:
        return None
    try:
        systolic = int(left)
        # Accept shorthand commonly used in PT-BR, e.g. 19/11 -> 190/110.
        if systolic <= 30:
            return systolic * 10
        return systolic
    except ValueError:
        return None


@router.get("/patients", response_model=PatientListResponse)
async def list_patients(
    status: str | None = None,
    q: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> PatientListResponse:
    patients = await patient_repo.list_patients(session, status=status, q=q)
    payload = [await patient_service.build_patient_schema(session, p) for p in patients]
    return PatientListResponse(patients=payload)


@router.post("/patients", response_model=PatientResponse, status_code=201)
async def create_patient(
    body: PatientCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> PatientResponse:
    patient = await patient_service.create_patient(session, body)
    await session.commit()
    set_patient_id(patient.id)
    clinical_audit(
        ClinicalAuditAction.ADMISSAO_PACIENTE,
        patient_id=patient.id,
        patient_name=patient.name,
        descricao=f"Paciente admitido ({patient.name}); idade {patient.age}; CID {patient.cid_code or '—'}.",
        detalhes={"cid": patient.cid_code or None, "idade": patient.age},
    )
    return PatientResponse(patient=await patient_service.build_patient_schema(session, patient))


@router.get("/patients/{patient_id}", response_model=PatientResponse)
async def get_patient(patient_id: str, session: AsyncSession = Depends(get_session)) -> PatientResponse:
    patient = await patient_repo.get_patient_by_id(session, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")
    return PatientResponse(patient=await patient_service.build_patient_schema(session, patient))


@router.get("/patients/{patient_id}/vitals-history", response_model=VitalSignsHistoryResponse)
async def get_vitals_history(
    patient_id: str,
    session: AsyncSession = Depends(get_session),
) -> VitalSignsHistoryResponse:
    patient = await patient_repo.get_patient_by_id(session, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    history = await patient_repo.list_vitals_history(session, patient_id)
    return VitalSignsHistoryResponse(
        history=[patient_service.vitals_to_schema(vitals) for vitals in history]
    )


@router.patch("/patients/{patient_id}", response_model=PatientResponse)
async def patch_patient(
    request: Request,
    patient_id: str,
    body: PatientPatchRequest,
    session: AsyncSession = Depends(get_session),
) -> PatientResponse:
    patient = await patient_repo.get_patient_by_id(session, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")
    prev_status = patient.status
    prev_code = (patient.cid_code or "").strip()
    prev_label = (patient.cid_label or "").strip()
    await patient_service.patch_patient(session, patient, body)
    await session.commit()
    await invalidate_patient_context(request.app.state, patient_id)

    if body.status is not None and prev_status != "discharged" and patient.status == "discharged":
        clinical_audit(
            ClinicalAuditAction.ALTA_PACIENTE,
            patient_id=patient.id,
            patient_name=patient.name,
            descricao=f"Alta registrada para {patient.name}.",
        )

    if body.cid is not None:
        new_code = (patient.cid_code or "").strip()
        new_label = (patient.cid_label or "").strip()
        prev_tuple = (prev_code, prev_label)
        new_tuple = (new_code, new_label)
        if prev_tuple != new_tuple:
            if prev_code and not new_code:
                clinical_audit(
                    ClinicalAuditAction.CID_REMOVIDO,
                    patient_id=patient.id,
                    patient_name=patient.name,
                    descricao=f"CID removido do prontuário de {patient.name}.",
                    detalhes={"cid_anterior": prev_code},
                )
            elif new_code:
                clinical_audit(
                    ClinicalAuditAction.CID_ATUALIZADO,
                    patient_id=patient.id,
                    patient_name=patient.name,
                    descricao=(
                        f"CID atualizado para {patient.name}: {new_code}"
                        + (f" — {new_label}" if new_label else "")
                        + "."
                    ),
                    detalhes={
                        "cid_anterior": prev_code or None,
                        "label_anterior": prev_label or None,
                        "cid_novo": new_code,
                        "label_novo": new_label or None,
                    },
                )

    return PatientResponse(patient=await patient_service.build_patient_schema(session, patient))


@router.patch("/patients/{patient_id}/vitals", response_model=PatientResponse)
async def patch_vitals(
    patient_id: str,
    body: VitalSignsPatchRequest,
    session: AsyncSession = Depends(get_session),
) -> PatientResponse:
    patient = await patient_repo.get_patient_by_id(session, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    new_vitals = await patient_service.append_vitals(session, patient=patient, patch=body)
    crit: list[str] = []

    if body.oxygen_saturation is not None:
        curr_critical = new_vitals.oxygen_saturation < 92
        if curr_critical:
            crit.append("oxigenacao")
            await alert_service.create_alert(
                session,
                patient.id,
                severity="critical",
                category="clinical",
                message=f"SpO2 crítico registrado ({new_vitals.oxygen_saturation}%).",
                team="doctors",
            )

    if body.temperature is not None:
        curr_critical = new_vitals.temperature >= 39 or new_vitals.temperature < 35
        if curr_critical:
            crit.append("temperatura")
            await alert_service.create_alert(
                session,
                patient.id,
                severity="critical",
                category="clinical",
                message=f"Temperatura crítica registrada ({new_vitals.temperature:.1f} °C).",
                team="doctors",
            )

    if body.heart_rate is not None:
        curr_critical = new_vitals.heart_rate > 120 or new_vitals.heart_rate < 45
        if curr_critical:
            crit.append("frequencia_cardiaca")
            await alert_service.create_alert(
                session,
                patient.id,
                severity="critical",
                category="clinical",
                message=f"Frequência cardíaca crítica registrada ({new_vitals.heart_rate} bpm).",
                team="doctors",
            )

    if body.blood_pressure is not None:
        curr_sys = _extract_systolic(new_vitals.blood_pressure)
        curr_critical = curr_sys is not None and curr_sys >= 180
        if curr_critical:
            crit.append("pressao_arterial")
            await alert_service.create_alert(
                session,
                patient.id,
                severity="critical",
                category="clinical",
                message=f"Pressão arterial crítica registrada ({new_vitals.blood_pressure}).",
                team="doctors",
            )

    demo = audit_context_is_demo()
    acao_v = (
        ClinicalAuditAction.SIMULACAO_SINAL_VITAL
        if demo
        else ClinicalAuditAction.SINAL_VITAL_REGISTRADO
    )
    detalhes: dict[str, object] = {
        "pa": str(new_vitals.blood_pressure or ""),
        "temperatura_c": float(new_vitals.temperature),
        "spo2": int(new_vitals.oxygen_saturation),
        "fc_bpm": int(new_vitals.heart_rate),
    }
    if crit:
        detalhes["gatilhos_criticos"] = crit

    tipo_txt = "Simulação de sinais vitais" if demo else "Sinais vitais registrados"
    clinical_audit(
        acao_v,
        patient_id=patient.id,
        patient_name=patient.name,
        descricao=f"{tipo_txt} para {patient.name}.",
        detalhes=detalhes if detalhes else None,
    )

    await session.commit()
    return PatientResponse(patient=await patient_service.build_patient_schema(session, patient))


@router.post("/patients/{patient_id}/readmit", response_model=PatientResponse)
async def readmit_patient(
    request: Request,
    patient_id: str,
    session: AsyncSession = Depends(get_session),
) -> PatientResponse:
    patient = await patient_repo.get_patient_by_id(session, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")
    if patient.status == "admitted":
        raise HTTPException(status_code=409, detail="Paciente já está admitido")

    await patient_service.readmit_patient(session, patient)
    await session.commit()
    await invalidate_patient_context(request.app.state, patient_id)
    clinical_audit(
        ClinicalAuditAction.READMISSAO_PACIENTE,
        patient_id=patient.id,
        patient_name=patient.name,
        descricao=f"Readmissão de {patient.name}; CID {(patient.cid_code or '').strip() or '—'}.",
    )
    return PatientResponse(patient=await patient_service.build_patient_schema(session, patient))


@router.post("/patients/{patient_id}/exams", response_model=ExamResponse, status_code=201)
async def create_manual_exam(
    request: Request,
    patient_id: str,
    body: ExamCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> ExamResponse:
    patient = await patient_repo.get_patient_by_id(session, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    exam = Exam(
        id=patient_service._new_id("ex"),
        patient_id=patient.id,
        name=body.name,
        status="pending",
        source="manual",
    )
    await exam_repo.create_exam(session, exam)
    await session.commit()
    await invalidate_patient_context(request.app.state, patient_id)
    clinical_audit(
        ClinicalAuditAction.NOVO_EXAME,
        patient_id=patient.id,
        patient_name=patient.name,
        descricao=f"Novo exame manual «{exam.name}» solicitado para {patient.name}.",
        detalhes={"exam_id": exam.id},
    )
    return ExamResponse(exam=await patient_service.exam_to_schema_with_attachments(session, exam))


@router.patch("/patients/{patient_id}/exams/{exam_id}", response_model=ExamResponse)
async def patch_exam(
    request: Request,
    patient_id: str,
    exam_id: str,
    body: ExamPatchRequest,
    session: AsyncSession = Depends(get_session),
) -> ExamResponse:
    exam = await exam_repo.get_exam_by_id(session, patient_id, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="Exame não encontrado")

    patient_row = await patient_repo.get_patient_by_id(session, patient_id)
    if patient_row is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    previous_status = exam.status

    if body.status is not None:
        exam.status = body.status
    if body.result is not None:
        exam.result = body.result
    if body.interpretation is not None:
        exam.interpretation = body.interpretation

    # Registra data de conclusão na primeira transição para completed/critical.
    if body.status in {"completed", "critical"} and exam.completed_at is None:
        exam.completed_at = datetime.now(UTC)

    if body.status == "critical" and previous_status != "critical":
        result_text = exam.result or "sem valor informado"
        await alert_service.create_alert(
            session,
            patient_id,
            severity="critical",
            category="exam",
            message=f"Resultado crítico registrado para {exam.name}: {result_text}.",
            team="doctors",
        )

    demo = audit_context_is_demo()
    acao_x = (
        ClinicalAuditAction.SIMULACAO_RESULTADO_EXAME
        if demo
        else ClinicalAuditAction.EXAME_ALTERADO
    )
    detalhes_x: dict[str, object] = {
        "exam_id": exam_id,
        "nome_exame": exam.name,
        "status_anterior": str(previous_status),
        "status_novo": str(exam.status),
    }
    if body.result is not None:
        detalhes_x["resultado"] = exam.result or ""
    if body.interpretation is not None:
        detalhes_x["interpretacao"] = exam.interpretation or ""
    prefix = "Simulação de resultado" if demo else "Exame atualizado"
    clinical_audit(
        acao_x,
        patient_id=patient_id,
        patient_name=patient_row.name,
        descricao=f"{prefix}: «{exam.name}» agora `{exam.status}`.",
        detalhes=detalhes_x,
    )

    await session.commit()
    await invalidate_patient_context(request.app.state, patient_id)
    return ExamResponse(exam=await patient_service.exam_to_schema_with_attachments(session, exam))


@router.post("/patients/{patient_id}/exams/{exam_id}/upload", response_model=ExamResponse)
async def upload_exam_file(
    patient_id: str,
    exam_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> ExamResponse:
    exam = await exam_repo.get_exam_by_id(session, patient_id, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="Exame não encontrado")
    if exam.source != "manual":
        raise HTTPException(status_code=400, detail="Upload permitido apenas para exame manual")

    patient_row = await patient_repo.get_patient_by_id(session, patient_id)
    if patient_row is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    settings = Settings()
    uploads_dir = Path(settings.uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    target = uploads_dir / f"{exam.id}_{file.filename}"
    content = await file.read()
    target.write_bytes(content)

    clinical_audit(
        ClinicalAuditAction.UPLOAD_EXAME_REALIZADO,
        patient_id=patient_id,
        patient_name=patient_row.name,
        descricao=f"Upload «{file.filename}» anexado ao exame «{exam.name}» ({patient_row.name}).",
        detalhes={
            "exam_id": exam_id,
            "arquivo": file.filename,
            "mime": str(file.content_type or "application/octet-stream"),
            "tamanho_bytes": len(content),
        },
    )

    # Criar novo registro de attachment ao invés de sobrescrever
    attachment = ExamAttachment(
        id=patient_service._new_id("att"),
        exam_id=exam.id,
        name=file.filename,
        mime=file.content_type or "application/octet-stream",
        size=len(content),
        path=str(target),
    )
    await attachment_repo.create_attachment(session, attachment)
    await session.commit()
    
    return ExamResponse(exam=await patient_service.exam_to_schema_with_attachments(session, exam))


@router.post("/patients/{patient_id}/suggested-items", response_model=SuggestedItemResponse, status_code=201)
async def create_suggested_item(
    patient_id: str,
    body: SuggestedItemCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> SuggestedItemResponse:
    patient = await patient_repo.get_patient_by_id(session, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    item = SuggestedItem(
        id=patient_service._new_id("sa"),
        patient_id=patient.id,
        type=body.type,
        description=body.description,
        status="suggested",
    )
    await suggested_item_repo.create_item(session, item)
    await session.commit()
    return SuggestedItemResponse(item=patient_service.suggested_item_to_schema(item))


@router.patch("/patients/{patient_id}/suggested-items/{item_id}", response_model=SuggestedItemResponse)
async def patch_suggested_item(
    patient_id: str,
    item_id: str,
    body: SuggestedItemPatchRequest,
    session: AsyncSession = Depends(get_session),
) -> SuggestedItemResponse:
    item = await suggested_item_repo.get_item_by_id(session, patient_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Ação sugerida não encontrada")

    patient = await patient_repo.get_patient_by_id(session, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    prev_status = item.status
    prev_description = item.description

    if body.status is not None:
        item.status = body.status
    if body.description is not None:
        item.description = body.description

    await session.commit()
    clinical_audit(
        ClinicalAuditAction.ACAO_SUGERIDA_ATUALIZADA,
        patient_id=patient_id,
        patient_name=patient.name,
        descricao=f"Ação sugerida «{item.type}» atualizada para {patient.name}.",
        detalhes={
            "item_id": item_id,
            "tipo": item.type,
            "status_anterior": prev_status,
            "status_novo": item.status,
            "descricao_anterior": prev_description,
            "descricao_nova": item.description,
        },
    )
    return SuggestedItemResponse(item=patient_service.suggested_item_to_schema(item))
