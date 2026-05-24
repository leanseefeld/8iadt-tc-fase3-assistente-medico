"""Observabilidade: logging em consola, correlação HTTP e auditoria clínica em JSONL."""

from assistente_medico_api.observability.audit import audit, mask_cpf, truncate
from assistente_medico_api.observability.clinical_audit_jsonl import ClinicalAuditAction, clinical_audit
from assistente_medico_api.observability.logging_setup import configure_logging

__all__ = ["ClinicalAuditAction", "audit", "clinical_audit", "configure_logging", "mask_cpf", "truncate"]
