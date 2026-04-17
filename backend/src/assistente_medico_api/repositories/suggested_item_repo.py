"""Data access helpers for suggested items."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from assistente_medico_api.models.suggested_item import SuggestedItem


async def create_item(session: AsyncSession, item: SuggestedItem) -> SuggestedItem:
    session.add(item)
    await session.flush()
    return item


async def create_many(session: AsyncSession, items: list[SuggestedItem]) -> None:
    session.add_all(items)
    await session.flush()


async def get_item_by_id(
    session: AsyncSession,
    patient_id: str,
    item_id: str,
) -> SuggestedItem | None:
    result = await session.execute(
        select(SuggestedItem).where(
            SuggestedItem.patient_id == patient_id,
            SuggestedItem.id == item_id,
        )
    )
    return result.scalar_one_or_none()
