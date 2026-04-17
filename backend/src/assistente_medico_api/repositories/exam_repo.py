"""Data access helpers for exams."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from assistente_medico_api.models.exam import Exam


async def create_exam(session: AsyncSession, exam: Exam) -> Exam:
    session.add(exam)
    await session.flush()
    return exam


async def create_many(session: AsyncSession, exams: list[Exam]) -> None:
    session.add_all(exams)
    await session.flush()


async def get_exam_by_id(session: AsyncSession, patient_id: str, exam_id: str) -> Exam | None:
    result = await session.execute(
        select(Exam).where(Exam.patient_id == patient_id, Exam.id == exam_id)
    )
    return result.scalar_one_or_none()
