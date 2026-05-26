"""Modelos estruturados para decisão LLM nos alertas clínicos (internos)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClinicalAlertLlmAssessment(BaseModel):
    """Saída JSON esperada da avaliação de risco (um registro pode virar vários alertas)."""

    should_alert: bool = Field(description="Emitir pelo menos um alerta clínico.")
    rationale: str = Field(default="", description="Justificativa curta.")
    alerts: list[dict] = Field(
        default_factory=list,
        description=(
            "Lista de alertas propostos. Cada item: severity, category, "
            "team, message."
        ),
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
