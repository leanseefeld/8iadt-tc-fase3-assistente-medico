"""Dependências compartilhadas: settings, vector store Chroma."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from assistente_medico_api.config import Settings
from assistente_medico_api.db.session import AsyncSessionLocal

if TYPE_CHECKING:
    from langchain_chroma import Chroma


def get_settings() -> Settings:
    """Instância única de configuração (lazy)."""
    return Settings()


def get_chroma_store(request: Request) -> Chroma:
    """Vector store inicializado no lifespan do app."""
    store = getattr(request.app.state, "chroma_store", None)
    if store is None:
        msg = "Chroma não inicializado; verifique o lifespan da aplicação."
        raise RuntimeError(msg)
    return store


async def get_session() -> AsyncIterator[AsyncSession]:
    """Async DB session for request-scoped data access."""
    async with AsyncSessionLocal() as session:
        yield session
