from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from assistente_medico_api.deps import get_session
from assistente_medico_api.main import create_app
from assistente_medico_api.models import (
    AgentLogEntry,
    Alert,
    Conversation,
    ConversationMessage,
    Exam,
    Patient,
    Prescription,
    SuggestedItem,
    VitalSigns,
)  # noqa: F401


_CLINICAL_AUDIT_ENV_KEY = "MEDICO_CLINICAL_AUDIT_ENABLED"
_clinical_audit_env_backup: tuple[bool, str] | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Não criar/atualizar `logs/audit_clinical_*.jsonl` durante a suíte de testes."""
    global _clinical_audit_env_backup  # noqa: PLW0603
    key = _CLINICAL_AUDIT_ENV_KEY
    had = key in os.environ
    prev = os.environ[key] if had else ""
    _clinical_audit_env_backup = (had, prev)
    os.environ[key] = "false"


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restaura o valor anterior de MEDICO_CLINICAL_AUDIT_ENABLED."""
    global _clinical_audit_env_backup  # noqa: PLW0603
    if _clinical_audit_env_backup is None:
        return
    key = _CLINICAL_AUDIT_ENV_KEY
    had, prev = _clinical_audit_env_backup
    if had:
        os.environ[key] = prev
    else:
        os.environ.pop(key, None)
    _clinical_audit_env_backup = None


@pytest_asyncio.fixture
async def test_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield SessionLocal
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def app(test_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[FastAPI]:
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def async_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def chat_patient(test_session_factory: async_sessionmaker[AsyncSession]):
    """Paciente mínimo para testes do endpoint de chat."""
    async with test_session_factory() as session:
        session.add(
            Patient(
                id="p1",
                name="Paciente Teste",
                age=40,
                sex="M",
                cid_code="A41.9",
                cid_label="Sepse",
                observations="",
            )
        )
        await session.commit()
