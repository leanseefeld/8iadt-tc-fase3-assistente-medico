"""Repository: prescriptions."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from assistente_medico_api.models.prescription import Prescription


async def create_prescription(session: AsyncSession, row: Prescription) -> Prescription:
    session.add(row)
    await session.flush()
    return row


async def get_prescription_by_id(session: AsyncSession, prescription_id: str) -> Prescription | None:
    statement = select(Prescription).where(Prescription.id == prescription_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def list_by_patient_id(
    session: AsyncSession,
    *,
    patient_id: str,
    include_archived: bool = False,
) -> list[Prescription]:
    statement = select(Prescription).where(Prescription.patient_id == patient_id)
    if not include_archived:
        statement = statement.where(col(Prescription.archived_at).is_(None))
    statement = statement.order_by(col(Prescription.issued_at).desc())
    result = await session.execute(statement)
    return list(result.scalars().all())


async def update_prescription(session: AsyncSession, row: Prescription) -> Prescription:
    session.add(row)
    await session.flush()
    return row
