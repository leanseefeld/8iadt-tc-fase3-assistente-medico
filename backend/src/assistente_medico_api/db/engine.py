"""Async SQLAlchemy engine for application runtime."""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

from assistente_medico_api.config import Settings, resolve_database_url

settings = Settings()

engine = create_async_engine(
    resolve_database_url(settings),
    connect_args={"timeout": 30},
    echo=False,
    future=True,
)


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_on_connect(dbapi_connection, _connection_record) -> None:
    """
    Configurações de concorrência do SQLite.

    - WAL: melhora a convivência entre leitores (GET) e um escritor (INSERT/UPDATE).
    - busy_timeout: evita falhas imediatas com "database is locked" sob concorrência.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=30000;")
    cursor.close()
