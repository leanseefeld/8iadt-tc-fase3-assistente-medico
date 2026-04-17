"""Data access helpers for exam attachments."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from assistente_medico_api.models.attachment import ExamAttachment


async def create_attachment(session: AsyncSession, attachment: ExamAttachment) -> ExamAttachment:
    session.add(attachment)
    await session.flush()
    return attachment


async def get_attachments_by_exam(
    session: AsyncSession, exam_id: str
) -> list[ExamAttachment]:
    result = await session.execute(
        select(ExamAttachment).where(ExamAttachment.exam_id == exam_id)
    )
    return result.scalars().all()
