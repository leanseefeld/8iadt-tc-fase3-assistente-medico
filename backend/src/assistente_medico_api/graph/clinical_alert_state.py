"""Estado do grafo LangGraph de avaliação de alertas clínicos (PCDT/RAG)."""

from __future__ import annotations

from typing import Literal, TypedDict


class InterpretedClinicalFlags(TypedDict, total=False):
    """Achados sintéticos usados pela etapa de decisão."""

    vital_flags: list[str]
    vital_messages: list[str]
    exam_status_critical: bool
    exam_name: str
    exam_result: str
    exam_interpretation: str
    high_risk_keywords_in_context: bool


class ClinicalAlertGraphState(TypedDict, total=False):
    """Estado compartilhado entre nós de alerta clínico."""

    run_id: str
    patient_id: str
    trigger_type: Literal["check_in", "exam_result", "vital_sign"]
    patient_bundle: dict
    exam_focus: dict | None
    latest_vitals: dict | None
    reasoning_steps: list[str]
    initial_query: str
    deep_query: str
    reference_rewrite: dict
    reference_retrieve: dict
    reference_rerank: dict
    reference_docs_text: str
    reference_sources: list[str]
    interpreted: InterpretedClinicalFlags
    patient_rewrite: dict
    patient_retrieve: dict
    patient_rerank: dict
    patient_docs_text: str
    patient_sources: list[str]
    assessments: list[dict]
    alert_payloads: list[dict]
    audit_trace: dict
