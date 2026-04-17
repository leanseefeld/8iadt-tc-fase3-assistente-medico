"""Data access helpers for alerts."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from assistente_medico_api.models.alert import Alert


async def create_alert(session: AsyncSession, alert: Alert) -> Alert:
    session.add(alert)
    await session.flush()
    return alert


async def create_many(session: AsyncSession, alerts: list[Alert]) -> None:
    session.add_all(alerts)
    await session.flush()


async def get_alert_by_id(session: AsyncSession, alert_id: str) -> Alert | None:
    result = await session.execute(
        select(Alert).where(Alert.id == alert_id)
    )
    return result.scalar_one_or_none()


async def list_alerts(
    session: AsyncSession,
    patient_id: str | None = None,
    resolved: bool | None = None,
    severity: str | None = None,
    team: str | None = None,
) -> list[Alert]:
    query = select(Alert)

    if patient_id is not None:
        query = query.where(Alert.patient_id == patient_id)

    if resolved is not None:
        query = query.where(Alert.resolved == resolved)

    if severity is not None:
        query = query.where(Alert.severity == severity)

    if team is not None:
        # Filter by exact team or 'all'
        query = query.where((Alert.team == team) | (Alert.team == "all"))

    query = query.order_by(Alert.created_at.desc())
    result = await session.execute(query)
    return result.scalars().all()


async def update_alert(session: AsyncSession, alert: Alert) -> Alert:
    session.add(alert)
    await session.flush()
    return alert


async def get_unresolved_count(session: AsyncSession) -> int:
    result = await session.execute(
        select(Alert).where(Alert.resolved == False)
    )
    return len(result.scalars().all())
