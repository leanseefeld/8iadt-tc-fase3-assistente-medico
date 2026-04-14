"""Dependências compartilhadas: settings, vector store Chroma."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from assistente_medico_api.config import Settings

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
