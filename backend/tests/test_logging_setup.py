"""Testes para logging estruturado JSON, middleware de request_id e helper `audit`."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from assistente_medico_api.main import create_app
from assistente_medico_api.observability.audit import audit
from assistente_medico_api.observability.context import (
    reset_request_id,
    set_request_id,
)
from assistente_medico_api.observability.json_formatter import JsonFormatter


def test_json_formatter_includes_standard_fields_and_extras():
    formatter = JsonFormatter()
    rid_tok = set_request_id("test-req-z9")
    try:
        record = logging.LogRecord(
            name="assistente_medico.http",
            level=logging.INFO,
            pathname="somewhere/api.py",
            lineno=42,
            msg="http_request",
            args=(),
            exc_info=None,
        )
        record.thread_id = "thread-aaa"
        record.patient_id = "patient-bbb"
        record.latency_ms = 33.44
        record.audit_extras = {"method": "GET", "path": "/x", "status": 200}
        raw = formatter.format(record)
    finally:
        reset_request_id(rid_tok)

    data = json.loads(raw)
    assert data["request_id"] == "test-req-z9"
    assert data["thread_id"] == "thread-aaa"
    assert data["patient_id"] == "patient-bbb"
    assert data["latency_ms"] == 33.44
    assert data["event"] == "http_request"
    assert data["level"] == "INFO"
    assert data["extras"]["method"] == "GET"


def test_audit_writes_parseable_json_line():
    import io

    lg = logging.getLogger("assistente_medico.audit.clinical")
    saved_handlers = list(lg.handlers)
    saved_propagate = lg.propagate
    saved_level = lg.level
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(JsonFormatter())
    try:
        lg.handlers.clear()
        lg.propagate = False
        lg.setLevel(logging.INFO)
        lg.addHandler(h)

        audit(
            "event_x",
            kind="clinical",
            patient_id="pt-sample",
            extra_field=123,
            text_snippet="ok",
        )

        data = json.loads(buf.getvalue().strip())
        assert data["event"] == "event_x"
        assert data["patient_id"] == "pt-sample"
        assert data["extras"]["extra_field"] == 123
        assert data["extras"]["text_snippet"] == "ok"
    finally:
        lg.removeHandler(h)
        lg.handlers[:] = saved_handlers
        lg.propagate = saved_propagate
        lg.setLevel(saved_level)


@pytest.mark.asyncio
async def test_middleware_echoes_x_request_id_openapi():
    app = create_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/openapi.json", headers={"X-Request-Id": "upstream-rid"})
    assert res.status_code == 200
    hdr = (
        res.headers.get("x-request-id")
        or res.headers.get("X-Request-Id")
        or ""
    )
    assert hdr == "upstream-rid"
