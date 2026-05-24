"""Testes para JsonFormatter legado, middleware de request_id e auditoria clínica JSONL."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import httpx
import pytest

from assistente_medico_api.config import Settings, resolve_runtime_path
from assistente_medico_api.main import create_app
from assistente_medico_api.observability.clinical_audit_jsonl import (
    ClinicalAuditAction,
    append_clinical_audit_line,
    clinical_audit,
)
from assistente_medico_api.observability.context import (
    reset_audit_context,
    reset_request_id,
    reset_user_id,
    set_audit_context,
    set_request_id,
    set_user_id,
)
from assistente_medico_api.observability.json_formatter import JsonFormatter


def test_json_formatter_includes_standard_fields_and_extras():
    formatter = JsonFormatter()
    rid_tok = set_request_id("test-req-z9")
    try:
        record = logging.LogRecord(
            name="assistente_medico.manual",
            level=logging.INFO,
            pathname="somewhere/api.py",
            lineno=42,
            msg="custom_event",
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
    assert data["event"] == "custom_event"


def test_clinical_audit_jsonl_shape_and_daily_file(tmp_path: Path):
    cfg = Settings(log_dir=tmp_path / "logs", clinical_audit_enabled=True)
    log_dir = resolve_runtime_path(cfg.log_dir)

    ctx_tok = set_audit_context("demo")
    uid_tok = set_user_id("doc-test-01")
    rid_inner = set_request_id("req-xyz")

    try:
        clinical_audit(
            ClinicalAuditAction.NOVO_EXAME,
            patient_id="pt-a",
            patient_name="Paciente Demo",
            descricao="Um exame novo (teste).",
            detalhes={"exam_id": "ex-1"},
            settings=cfg,
        )
        today = date.today().isoformat()
        path = log_dir / f"audit_clinical_{today}.jsonl"
        assert path.is_file()
        line = path.read_text(encoding="utf-8").strip()
        data = json.loads(line)
        assert data["acao"] == "novo_exame"
        assert data["medico_id"] == "doc-test-01"
        assert data["request_id"] == "req-xyz"
        assert data["patient_id"] == "pt-a"
        assert "ts" not in data
        assert "level" not in data
        assert "logger" not in data
        assert "detalhes" in data
    finally:
        reset_request_id(rid_inner)
        reset_user_id(uid_tok)
        reset_audit_context(ctx_tok)


def test_append_clinical_audit_line_accepts_plain_dict(tmp_path: Path):
    cfg = Settings(log_dir=tmp_path / "zlogs", clinical_audit_enabled=True)
    append_clinical_audit_line(cfg, {"acao": "x", "descricao": "y"})
    p = resolve_runtime_path(cfg.log_dir) / f"audit_clinical_{date.today().isoformat()}.jsonl"
    assert json.loads(p.read_text(encoding="utf-8").strip())["acao"] == "x"


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
