"""Compila o grafo LangGraph de alertas clínicos (consultas aos PCDTs)."""

from __future__ import annotations

from uuid import uuid4

from langchain_chroma import Chroma
from langgraph.graph import END, StateGraph

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.alert_nodes.assess import node_assess_and_prepare_alerts
from assistente_medico_api.graph.alert_nodes.build_query import node_build_queries
from assistente_medico_api.graph.alert_nodes.interpret import node_interpret_local
from assistente_medico_api.graph.alert_nodes.retrieve import (
    node_retrieve_patient_context,
    node_retrieve_reference,
)
from assistente_medico_api.graph.clinical_alert_state import ClinicalAlertGraphState


def build_compiled_clinical_alert_graph(store: Chroma | None, settings: Settings):  # type: ignore[no-untyped-def]
    """Compila pipeline linear multi-nó: consultas + duas recuperações + decisão."""

    async def _build_queries(state: ClinicalAlertGraphState) -> dict:
        return node_build_queries(state)

    async def _reference(state: ClinicalAlertGraphState) -> dict:
        if store is None:
            steps = list(state.get("reasoning_steps") or [])
            steps.append("Vectorstore ausente nesta sessão — pulando primeira recuperação.")
            return {
                "reference_docs_text": "",
                "reference_sources": [],
                "reasoning_steps": steps,
                "reference_rewrite": {},
                "reference_retrieve": {},
                "reference_rerank": {},
            }
        try:
            return await node_retrieve_reference(state, store=store, settings=settings)
        except Exception as exc:  # noqa: BLE001
            steps = list(state.get("reasoning_steps") or [])
            steps.append(f"Erro na primeira recuperação PCDT ({type(exc).__name__}); seguindo sem contexto inicial.")
            return {
                "reference_docs_text": "",
                "reference_sources": [],
                "reasoning_steps": steps,
                "reference_rewrite": {},
                "reference_retrieve": {},
                "reference_rerank": {},
            }

    def _interpret(state: ClinicalAlertGraphState) -> dict:
        return node_interpret_local(state)

    async def _patient_retrieve(state: ClinicalAlertGraphState) -> dict:
        if store is None:
            steps = list(state.get("reasoning_steps") or [])
            steps.append("Vectorstore ausente — pulando segunda recuperação contextual.")
            return {
                "patient_docs_text": "",
                "patient_sources": [],
                "reasoning_steps": steps,
                "patient_rewrite": {},
                "patient_retrieve": {},
                "patient_rerank": {},
            }
        try:
            return await node_retrieve_patient_context(state, store=store, settings=settings)
        except Exception as exc:  # noqa: BLE001
            steps = list(state.get("reasoning_steps") or [])
            steps.append(f"Erro na segunda recuperação PCDT ({type(exc).__name__}); seguindo apenas com primeira passagem/heurísticas.")
            return {
                "patient_docs_text": "",
                "patient_sources": [],
                "reasoning_steps": steps,
                "patient_rewrite": {},
                "patient_retrieve": {},
                "patient_rerank": {},
            }

    async def _assess(state: ClinicalAlertGraphState) -> dict:
        return await node_assess_and_prepare_alerts(state, settings=settings)

    workflow = StateGraph(ClinicalAlertGraphState)
    workflow.add_node("build_queries", _build_queries)
    workflow.add_node("retrieve_reference_pcdt", _reference)
    workflow.add_node("interpret_local_signals", _interpret)
    workflow.add_node("retrieve_patient_pcdt", _patient_retrieve)
    workflow.add_node("assess_alert_payloads", _assess)
    workflow.set_entry_point("build_queries")
    workflow.add_edge("build_queries", "retrieve_reference_pcdt")
    workflow.add_edge("retrieve_reference_pcdt", "interpret_local_signals")
    workflow.add_edge("interpret_local_signals", "retrieve_patient_pcdt")
    workflow.add_edge("retrieve_patient_pcdt", "assess_alert_payloads")
    workflow.add_edge("assess_alert_payloads", END)
    return workflow.compile()


def seed_run_state(
    *,
    patient_id: str,
    trigger_type: str,
    patient_bundle: dict,
    exam_focus: dict | None = None,
    latest_vitals: dict | None = None,
) -> ClinicalAlertGraphState:
    """Estado inicial padrão (run_id será substituível por chamador externo)."""
    return {
        "run_id": str(uuid4()),
        "patient_id": patient_id,
        "trigger_type": trigger_type,  # type: ignore[typeddict-item]
        "patient_bundle": patient_bundle,
        "exam_focus": exam_focus,
        "latest_vitals": latest_vitals,
        "reasoning_steps": [],
        "alert_payloads": [],
        "interpreted": {},
    }
