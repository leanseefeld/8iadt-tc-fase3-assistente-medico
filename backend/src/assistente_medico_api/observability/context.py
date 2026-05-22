"""Context vars para correlacionar requisição HTTP com eventos de auditoria."""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_thread_id_var: ContextVar[str | None] = ContextVar("thread_id", default=None)
_patient_id_var: ContextVar[str | None] = ContextVar("patient_id", default=None)
_user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)


def new_request_id() -> str:
    """Gera um identificador curto para correlacionar logs dentro de uma requisição."""
    return uuid.uuid4().hex[:16]


def get_request_id() -> str | None:
    """Retorna o request_id atual ou None."""
    return _request_id_var.get()


def set_request_id(value: str | None) -> Token[str | None]:
    """Define request_id para o ContextVar atual; retorna token para reset."""
    return _request_id_var.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    """Restaura valor anterior do request_id."""
    _request_id_var.reset(token)


def get_thread_id() -> str | None:
    return _thread_id_var.get()


def set_thread_id(value: str | None) -> Token[str | None]:
    return _thread_id_var.set(value)


def reset_thread_id(token: Token[str | None]) -> None:
    _thread_id_var.reset(token)


def get_patient_id() -> str | None:
    return _patient_id_var.get()


def set_patient_id(value: str | None) -> Token[str | None]:
    return _patient_id_var.set(value)


def reset_patient_id(token: Token[str | None]) -> None:
    _patient_id_var.reset(token)


def get_user_id() -> str | None:
    return _user_id_var.get()


def set_user_id(value: str | None) -> Token[str | None]:
    return _user_id_var.set(value)


def reset_user_id(token: Token[str | None]) -> None:
    _user_id_var.reset(token)


def clear_assistant_scope() -> None:
    """Limpa IDs de fluxo definidos durante tratamento da requisição (evita vazamento entre requests)."""
    _thread_id_var.set(None)
    _patient_id_var.set(None)
