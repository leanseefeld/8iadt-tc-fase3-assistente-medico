"""Helpers de auditoria: eventos estruturados, truncamento e mascaramento de PII."""

from __future__ import annotations

import logging
import re
from typing import Any

from assistente_medico_api.observability.context import get_patient_id, get_thread_id

_CPF_DIGITS_RE = re.compile(r"\D+")


def truncate(text: str | None, n: int = 200) -> str:
    """Trunca texto livre para snippets em log (evita payload enorme)."""
    if not text:
        return ""
    t = text.strip()
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def mask_cpf(value: str | None) -> str | None:
    """
    Mascara CPF para log: mantém apenas os 2 últimos dígitos como `XXX.XXX.XXX-NN`.
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    digits = _CPF_DIGITS_RE.sub("", raw)
    if len(digits) != 11:
        return "*** (CPF formato inválido)"
    return f"XXX.XXX.XXX-{digits[-2:]}"


def _logger_name_for_kind(kind: str) -> str:
    """Mapeia tipo lógico (`kind`) para namespace de logger estável."""
    k = (kind or "").strip().lower()
    if k == "clinical":
        return "assistente_medico.audit.clinical"
    if k == "chat":
        return "assistente_medico.chat"
    if k == "http":
        return "assistente_medico.http"
    if k == "rag" or k.startswith("rag."):
        return "assistente_medico.audit.rag"
    return "assistente_medico.audit"


def audit(
    event: str,
    *,
    kind: str,
    level: int = logging.INFO,
    thread_id: str | None = None,
    patient_id: str | None = None,
    latency_ms: float | None = None,
    **extras: Any,
) -> None:
    """
    Registra evento de auditoria com JSON unificado (via JsonFormatter).

    Campos `thread_id` e `patient_id` usam ContextVar quando omitidos.
    """
    log = logging.getLogger(_logger_name_for_kind(kind))
    tid = thread_id if thread_id is not None else get_thread_id()
    pid = patient_id if patient_id is not None else get_patient_id()
    merged_extras = dict(extras) if extras else {}
    log.log(
        level,
        event,
        extra={
            "thread_id": tid,
            "patient_id": pid,
            "latency_ms": latency_ms,
            "audit_extras": merged_extras,
        },
    )
