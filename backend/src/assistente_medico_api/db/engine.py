"""Async SQLAlchemy engine for application runtime."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine

from assistente_medico_api.config import Settings

settings = Settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)
