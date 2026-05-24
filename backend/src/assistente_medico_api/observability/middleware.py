"""Middleware: request_id (header ou gerado) e contexto de auditoria opcional."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from assistente_medico_api.observability.context import (
    clear_assistant_scope,
    new_request_id,
    reset_audit_context,
    reset_patient_id,
    reset_request_id,
    reset_user_id,
    set_audit_context,
    set_patient_id,
    set_request_id,
    set_user_id,
)

# Extrai patient_id de paths como /api/patients/{id}/...
import re as _re

_PATIENT_PATH_RE = _re.compile(r"/patients/([^/]+)")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Associa `request_id` e `audit_context` ao ContextVar."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        hdr = request.headers.get("X-Request-Id") or request.headers.get("x-request-id")
        rid = hdr.strip() if hdr and hdr.strip() else new_request_id()
        rid_token = set_request_id(rid)

        raw_uid = request.headers.get("X-User-Id") or request.headers.get("x-user-id")
        uid = raw_uid.strip() if raw_uid and raw_uid.strip() else None
        uid_token = set_user_id(uid)

        raw_ctx = request.headers.get("X-Audit-Context") or request.headers.get("x-audit-context")
        audit_ctx_val = raw_ctx.strip() if raw_ctx and raw_ctx.strip() else None
        audit_ctx_token = set_audit_context(audit_ctx_val)

        m = _PATIENT_PATH_RE.search(request.url.path)
        pid_token = set_patient_id(m.group(1) if m else None)

        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = rid
            return response
        finally:
            reset_request_id(rid_token)
            reset_user_id(uid_token)
            reset_audit_context(audit_ctx_token)
            reset_patient_id(pid_token)
            clear_assistant_scope()
