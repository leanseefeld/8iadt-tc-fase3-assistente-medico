"""Patient business rules and DTO mapping helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from assistente_medico_api.models.agent_log import AgentLogEntry
from assistente_medico_api.models.exam import Exam
from assistente_medico_api.models.patient import Patient, VitalSigns
from assistente_medico_api.models.suggested_item import SuggestedItem
from assistente_medico_api.repositories import exam_repo, patient_repo, suggested_item_repo, attachment_repo
from assistente_medico_api.schemas.cids import Cid
from assistente_medico_api.schemas.exams import Exam as ExamSchema, ExamAttachment as ExamAttachmentSchema
from assistente_medico_api.schemas.patients import (
	AgentLogEntry as AgentLogEntrySchema,
	Patient as PatientSchema,
	PatientCreateRequest,
	PatientPatchRequest,
	VitalSigns as VitalSignsSchema,
	VitalSignsPatchRequest,
)
from assistente_medico_api.schemas.suggested_items import SuggestedItem as SuggestedItemSchema
from assistente_medico_api.services.protocol_map import get_protocol_for_cid


def _new_id(prefix: str) -> str:
	return f"{prefix}-{uuid4()}"


def _now() -> datetime:
	return datetime.now(UTC)


def _normalize_age(age: int | None) -> int:
	if age is None:
		return 45
	return min(120, max(0, age))


def _parse_medications(text: str | None) -> list[str]:
	if not text:
		return []
	lines = [line.strip() for line in text.split("\n")]
	return [line for line in lines if line]


async def _add_agent_log(
	session: AsyncSession,
	*,
	patient_id: str,
	step: str,
	status: str,
	detail: str,
) -> None:
	session.add(
		AgentLogEntry(
			patient_id=patient_id,
			step=step,
			status=status,
			detail=detail,
			timestamp=_now(),
		)
	)
	await session.flush()


async def append_vitals(
	session: AsyncSession,
	*,
	patient: Patient,
	patch: VitalSignsPatchRequest | None = None,
) -> VitalSigns:
	last = await patient_repo.get_latest_vitals(session, patient.id)
	blood_pressure = patch.blood_pressure if patch and patch.blood_pressure is not None else "120/80"
	temperature = patch.temperature if patch and patch.temperature is not None else 36.5
	oxygen_saturation = (
		patch.oxygen_saturation if patch and patch.oxygen_saturation is not None else 97
	)
	heart_rate = patch.heart_rate if patch and patch.heart_rate is not None else 72

	if last is not None:
		if patch is None:
			blood_pressure = last.blood_pressure
			temperature = last.temperature
			oxygen_saturation = last.oxygen_saturation
			heart_rate = last.heart_rate
		else:
			blood_pressure = patch.blood_pressure if patch.blood_pressure is not None else last.blood_pressure
			temperature = patch.temperature if patch.temperature is not None else last.temperature
			oxygen_saturation = (
				patch.oxygen_saturation
				if patch.oxygen_saturation is not None
				else last.oxygen_saturation
			)
			heart_rate = patch.heart_rate if patch.heart_rate is not None else last.heart_rate

	vitals = VitalSigns(
		patient_id=patient.id,
		blood_pressure=blood_pressure,
		temperature=float(temperature),
		oxygen_saturation=int(oxygen_saturation),
		heart_rate=int(heart_rate),
		recorded_at=_now(),
	)
	session.add(vitals)
	await session.flush()
	return vitals


async def apply_protocol(session: AsyncSession, patient: Patient, step: str) -> None:
	protocol = get_protocol_for_cid(patient.cid_code)
	now = _now()

	exams = [
		Exam(
			id=_new_id("ex"),
			patient_id=patient.id,
			name=name,
			requested_at=now,
			status="pending",
			source="protocol",
			protocol_ref=protocol.protocol_ref,
		)
		for name in protocol.exams
	]
	await exam_repo.create_many(session, exams)

	items = [
		SuggestedItem(
			id=_new_id("sa"),
			patient_id=patient.id,
			type=item.type,
			description=item.description,
			status="suggested",
			protocol_ref=protocol.protocol_ref,
		)
		for item in protocol.suggested_actions
	]
	await suggested_item_repo.create_many(session, items)

	await _add_agent_log(
		session,
		patient_id=patient.id,
		step=step,
		status="done",
		detail=f"Protocolo aplicado para CID {patient.cid_code}",
	)


async def create_patient(session: AsyncSession, body: PatientCreateRequest) -> Patient:
	now = _now()
	patient = Patient(
		id=_new_id("pt"),
		name=(body.name or "Paciente sem nome").strip() or "Paciente sem nome",
		age=_normalize_age(body.age),
		sex=body.sex or "M",
		status="admitted",
		admitted_at=now,
		cid_code=body.cid.code,
		cid_label=body.cid.label,
		observations=(body.observations or "Não informado").strip() or "Não informado",
		comorbidities=list(body.comorbidities or []),
		current_medications=_parse_medications(body.current_medications),
	)
	await patient_repo.create_patient(session, patient)
	await append_vitals(session, patient=patient)
	await apply_protocol(session, patient, "admission")
	await session.flush()
	return patient


async def change_cid(session: AsyncSession, patient: Patient, cid: Cid) -> None:
	patient.cid_code = cid.code
	patient.cid_label = cid.label
	await patient_repo.delete_patient_children(session, patient.id)
	await apply_protocol(session, patient, "cid-update")
	await session.flush()


async def patch_patient(session: AsyncSession, patient: Patient, patch: PatientPatchRequest) -> Patient:
	if patch.name is not None:
		patient.name = patch.name
	if patch.age is not None:
		patient.age = _normalize_age(patch.age)
	if patch.sex is not None:
		patient.sex = patch.sex
	if patch.status is not None:
		patient.status = patch.status
	if patch.observations is not None:
		patient.observations = patch.observations
	if patch.comorbidities is not None:
		patient.comorbidities = patch.comorbidities
	if patch.current_medications is not None:
		patient.current_medications = patch.current_medications
	if patch.cid is not None and patch.cid.code != patient.cid_code:
		await change_cid(session, patient, patch.cid)
	await session.flush()
	return patient


async def readmit_patient(session: AsyncSession, patient: Patient) -> Patient:
	patient.status = "admitted"
	patient.admitted_at = _now()
	await patient_repo.delete_patient_children(session, patient.id)
	await append_vitals(session, patient=patient)
	await apply_protocol(session, patient, "readmission")
	await session.flush()
	return patient


def exam_to_schema(exam: Exam) -> ExamSchema:
	return ExamSchema.model_validate({
		"id": exam.id,
		"name": exam.name,
		"requestedAt": exam.requested_at,
		"status": exam.status,
		"result": exam.result,
		"interpretation": exam.interpretation,
		"source": exam.source,
		"protocolRef": exam.protocol_ref,
		"attachments": [],
	})


async def exam_to_schema_with_attachments(
	session: AsyncSession, exam: Exam
) -> ExamSchema:
	attachments = await attachment_repo.get_attachments_by_exam(session, exam.id)
	return ExamSchema.model_validate({
		"id": exam.id,
		"name": exam.name,
		"requestedAt": exam.requested_at,
		"status": exam.status,
		"result": exam.result,
		"interpretation": exam.interpretation,
		"source": exam.source,
		"protocolRef": exam.protocol_ref,
		"attachments": [
			{"name": a.name, "mime": a.mime, "size": a.size, "path": a.path}
			for a in attachments
		],
	})


def suggested_item_to_schema(item: SuggestedItem) -> SuggestedItemSchema:
	return SuggestedItemSchema.model_validate(item.model_dump())


def log_to_schema(log: AgentLogEntry) -> AgentLogEntrySchema:
	return AgentLogEntrySchema.model_validate(log.model_dump())


def vitals_to_schema(vitals: VitalSigns) -> VitalSignsSchema:
	return VitalSignsSchema(
		bloodPressure=vitals.blood_pressure,
		temperature=vitals.temperature,
		oxygenSaturation=vitals.oxygen_saturation,
		heartRate=vitals.heart_rate,
		updatedAt=vitals.recorded_at,
	)


async def build_patient_schema(session: AsyncSession, patient: Patient) -> PatientSchema:
	vitals = await patient_repo.get_latest_vitals(session, patient.id)
	if vitals is None:
		vitals = await append_vitals(session, patient=patient)

	exams = await patient_repo.list_exams(session, patient.id)
	items = await patient_repo.list_suggested_items(session, patient.id)
	logs = await patient_repo.list_agent_logs(session, patient.id)

	exams_with_attachments = [
		await exam_to_schema_with_attachments(session, exam) for exam in exams
	]

	return PatientSchema(
		id=patient.id,
		name=patient.name,
		age=patient.age,
		sex=patient.sex,
		status=patient.status,
		admittedAt=patient.admitted_at,
		cid=Cid(code=patient.cid_code, label=patient.cid_label),
		observations=patient.observations,
		comorbidities=patient.comorbidities,
		currentMedications=patient.current_medications,
		vitalSigns=vitals_to_schema(vitals),
		exams=exams_with_attachments,
		suggestedItems=[suggested_item_to_schema(item) for item in items],
		agentLog=[log_to_schema(log) for log in logs],
	)
