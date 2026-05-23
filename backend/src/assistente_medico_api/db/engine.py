"""Async SQLAlchemy engine for application runtime."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine

from assistente_medico_api.config import Settings, resolve_database_url

settings = Settings()

engine = create_async_engine(
    resolve_database_url(settings),
    echo=False,
    future=True,
)
