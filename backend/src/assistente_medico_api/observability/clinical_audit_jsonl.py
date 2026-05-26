"""Auditoria clínica append-only em JSONL, um ficheiro por dia sob `logs/`."""

from __future__ import annotations

import json
import threading
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from assistente_medico_api.config import Settings, resolve_runtime_path
from assistente_medico_api.observability.context import get_audit_context, get_request_id, get_user_id

_WRITE_LOCK = threading.Lock()

# Valor de cabeçalho `X-Audit-Context: demo` usado para distinguir simulações da UI.
AUDIT_CONTEXT_DEMO = "demo"


def audit_context_is_demo() -> bool:
    """True quando o cliente enviou `X-Audit-Context: demo` (simulações do protótipo)."""
    return (get_audit_context() or "").strip().lower() == AUDIT_CONTEXT_DEMO


class ClinicalAuditAction(StrEnum):
    """Ações persistidas no diário clínico (campo `acao`)."""

    ADMISSAO_PACIENTE = "admissao_paciente"
    READMISSAO_PACIENTE = "readmissao_paciente"
    ALTA_PACIENTE = "alta_paciente"
    CID_ATUALIZADO = "cid_atualizado"
    CID_REMOVIDO = "cid_removido"
    NOVO_EXAME = "novo_exame"
    EXAME_ALTERADO = "exame_alterado"
    SIMULACAO_RESULTADO_EXAME = "simulacao_resultado_exame"
    UPLOAD_EXAME_REALIZADO = "upload_exame_realizado"
    SINAL_VITAL_REGISTRADO = "sinal_vital_registrado"
    SIMULACAO_SINAL_VITAL = "simulacao_sinal_vital"
    ALERTA_EMITIDO = "alerta_emitido"
    AVALIACAO_ALERTA_CLINICO_PCDT = "avaliacao_alerta_clinico_pcdt"
    ALERTA_RESOLVIDO = "alerta_resolvido"
    ACAO_SUGERIDA_ATUALIZADA = "acao_sugerida_atualizada"
    PRESCRICAO_EMITIDA = "prescricao_emitida"
    PRESCRICAO_ARQUIVADA = "prescricao_arquivada"
    EXECUCAO_FLUXO_DECISAO = "execucao_fluxo_decisao"
    # Eventos operacionais (RAG/backend) registados também no mesmo JSONL clínico,
    # em schema enxuto (detalhes resumidos) — migração dos antigos audit() só técnicos.
    BACKEND_ASSISTENTE_INICIADO = "backend_assistente_iniciado"
    REESCRITA_CONSULTA_RAG = "reescrita_consulta_rag"
    RECUPERACAO_CONTEXTO_RAG = "recuperacao_contexto_rag"
    GERACAO_RESPOSTA_RAG = "geracao_resposta_rag"
    GUARDRAIL_AVALIADO = "guardrail_avaliado"
    CONVERSA_ASSISTENTE_SOLICITADA = "conversa_assistente_solicitada"
    CONVERSA_ASSISTENTE_FINALIZADA = "conversa_assistente_finalizada"


def _audit_file_path(log_dir: Path, day: date) -> Path:
    return log_dir / f"audit_clinical_{day.isoformat()}.jsonl"


def append_clinical_audit_line(settings: Settings, payload: dict[str, Any]) -> None:
    """
    Escreve uma linha JSON no ficheiro do dia corrente (data local do processo).

    Cria o ficheiro se ainda não existir; thread-safe.
    """
    if not settings.clinical_audit_enabled:
        return
    log_dir = resolve_runtime_path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = _audit_file_path(log_dir, date.today())
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    with _WRITE_LOCK:
        path.open("a", encoding="utf-8").write(line)


def clinical_audit(
    acao: ClinicalAuditAction | str,
    *,
    patient_id: str | None = None,
    patient_name: str | None = None,
    descricao: str,
    detalhes: dict[str, Any] | None = None,
    medico_id: str | None = None,
    request_id: str | None = None,
    settings: Settings | None = None,
) -> None:
    """
    Monta o registro enxuto e grava em `audit_clinical_YYYY-MM-DD.jsonl`.

    `medico_id` e `request_id` tomam valores dos ContextVars quando omitidos.
    """
    cfg = settings if settings is not None else Settings()
    if not cfg.clinical_audit_enabled:
        return
    mid = medico_id if medico_id is not None else get_user_id()
    rid = request_id if request_id is not None else get_request_id()

    action_str = str(acao.value) if isinstance(acao, ClinicalAuditAction) else str(acao)

    payload: dict[str, Any] = {
        "acao": action_str,
        "medico_id": mid,
        "patient_id": patient_id,
        "patient_name": patient_name,
        "descricao": descricao,
    }
    if detalhes:
        payload["detalhes"] = detalhes
    if rid:
        payload["request_id"] = rid

    # Remove chaves com valor None (mantém ausência ou null conforme uso).
    trimmed = {k: v for k, v in payload.items() if v is not None}
    append_clinical_audit_line(cfg, trimmed)
