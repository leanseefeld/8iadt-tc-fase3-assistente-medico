"""Data access helpers for patients and aggregate reads."""

from __future__ import annotations

from sqlalchemy import desc, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from assistente_medico_api.models.agent_log import AgentLogEntry
from assistente_medico_api.models.exam import Exam
from assistente_medico_api.models.patient import Patient, VitalSigns
from assistente_medico_api.models.suggested_item import SuggestedItem


async def create_patient(session: AsyncSession, patient: Patient) -> Patient:
    session.add(patient)
    await session.flush()
    return patient


async def list_patients(
    session: AsyncSession,
    *,
    status: str | None = None,
    q: str | None = None,
) -> list[Patient]:
    query = select(Patient)
    if status:
        query = query.where(Patient.status == status)
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(Patient.name.ilike(pattern), Patient.id.ilike(pattern)))
    result = await session.execute(query.order_by(desc(Patient.admitted_at)))
    return list(result.scalars().all())


async def get_patient_by_id(session: AsyncSession, patient_id: str) -> Patient | None:
    result = await session.execute(select(Patient).where(Patient.id == patient_id))
    return result.scalar_one_or_none()


async def get_latest_vitals(session: AsyncSession, patient_id: str) -> VitalSigns | None:
    query = (
        select(VitalSigns)
        .where(VitalSigns.patient_id == patient_id)
        .order_by(desc(VitalSigns.recorded_at), desc(VitalSigns.id))
        .limit(1)
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def list_exams(session: AsyncSession, patient_id: str) -> list[Exam]:
    result = await session.execute(
        select(Exam).where(Exam.patient_id == patient_id).order_by(desc(Exam.requested_at))
    )
    return list(result.scalars().all())


async def list_suggested_items(session: AsyncSession, patient_id: str) -> list[SuggestedItem]:
    result = await session.execute(
        select(SuggestedItem)
        .where(SuggestedItem.patient_id == patient_id)
        .order_by(SuggestedItem.id)
    )
    return list(result.scalars().all())


async def list_agent_logs(session: AsyncSession, patient_id: str) -> list[AgentLogEntry]:
    result = await session.execute(
        select(AgentLogEntry)
        .where(AgentLogEntry.patient_id == patient_id)
        .order_by(desc(AgentLogEntry.timestamp), desc(AgentLogEntry.id))
    )
    return list(result.scalars().all())


async def delete_patient_children(session: AsyncSession, patient_id: str) -> None:
    await session.execute(delete(Exam).where(Exam.patient_id == patient_id))
    await session.execute(delete(SuggestedItem).where(SuggestedItem.patient_id == patient_id))
