"""Middleware: request_id (header ou gerado) + log `http_request` ao final."""

from __future__ import annotations

import logging
import re
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from assistente_medico_api.observability.audit import audit
from assistente_medico_api.observability.context import (
    clear_assistant_scope,
    new_request_id,
    reset_patient_id,
    reset_request_id,
    reset_user_id,
    set_patient_id,
    set_request_id,
    set_user_id,
)

# Extrai patient_id de paths como /api/patients/{id}/...
_PATIENT_PATH_RE = re.compile(r"/patients/([^/]+)")

# Janela de deduplicação: ignora logs de http_request idênticos dentro deste intervalo.
# Elimina ruído causado pelo React StrictMode (duplo effect) e componentes redundantes.
_DEDUP_WINDOW_S = 0.25
_dedup_cache: dict[tuple, float] = {}


def _should_log(method: str, path: str, uid: str | None) -> bool:
    """Retorna True se o evento deve ser registrado; False se é duplicata recente."""
    now = time.monotonic()
    key = (method, path, uid)

    # Limpa entradas antigas antes de verificar (evita crescimento ilimitado).
    expired = [k for k, t in _dedup_cache.items() if now - t > _DEDUP_WINDOW_S]
    for k in expired:
        del _dedup_cache[k]

    if key in _dedup_cache:
        return False
    _dedup_cache[key] = now
    return True


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Associa `request_id` ao ContextVar e registra latência HTTP."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        hdr = request.headers.get("X-Request-Id") or request.headers.get("x-request-id")
        rid = hdr.strip() if hdr and hdr.strip() else new_request_id()
        rid_token = set_request_id(rid)

        raw_uid = request.headers.get("X-User-Id") or request.headers.get("x-user-id")
        uid = raw_uid.strip() if raw_uid and raw_uid.strip() else None
        uid_token = set_user_id(uid)

        # Propaga patient_id para o ContextVar quando visível na URL.
        m = _PATIENT_PATH_RE.search(request.url.path)
        pid_token = set_patient_id(m.group(1) if m else None)

        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = getattr(response, "status_code", 200)
            # Propaga o mesmo id para o cliente correlacionar logs.
            response.headers["X-Request-Id"] = rid
            return response
        finally:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            if _should_log(request.method, request.url.path, uid):
                client_ip = request.client.host if request.client else None
                audit(
                    "http_request",
                    kind="http",
                    level=logging.INFO,
                    latency_ms=latency_ms,
                    method=request.method,
                    path=request.url.path,
                    status=status,
                    client_ip=client_ip,
                )
            reset_request_id(rid_token)
            reset_user_id(uid_token)
            reset_patient_id(pid_token)
            clear_assistant_scope()
