"""Observabilidade: logging JSON, correlação HTTP e auditoria."""

from assistente_medico_api.observability.audit import audit, mask_cpf, truncate
from assistente_medico_api.observability.logging_setup import configure_logging

__all__ = ["audit", "configure_logging", "mask_cpf", "truncate"]
