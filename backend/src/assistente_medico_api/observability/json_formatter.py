"""Formatter logging que emite uma linha JSON por registro (stdout / arquivo)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from assistente_medico_api.observability.context import get_request_id, get_user_id


class JsonFormatter(logging.Formatter):
    """Serializa `LogRecord` em JSON com campos padronizados de auditoria."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).isoformat().replace("+00:00", "Z")
        extras = getattr(record, "audit_extras", None)
        if not isinstance(extras, dict):
            extras = {}

        payload: dict = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": get_request_id(),
            "user_id": get_user_id(),
            "extras": extras,
        }
        tid = getattr(record, "thread_id", None)
        if tid is not None:
            payload["thread_id"] = tid
        pid = getattr(record, "patient_id", None)
        if pid is not None:
            payload["patient_id"] = pid
        lat = getattr(record, "latency_ms", None)
        if lat is not None:
            payload["latency_ms"] = lat

        return json.dumps(payload, ensure_ascii=False, default=str)
