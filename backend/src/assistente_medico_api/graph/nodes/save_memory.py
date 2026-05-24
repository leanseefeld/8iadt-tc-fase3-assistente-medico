"""LangGraph node: persist final turn memory after guardrail."""

from __future__ import annotations

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit
from assistente_medico_api.services.rag_pipeline_service import build_pipeline_audit, run_save_memory


def save_memory_node(state: ChatRAGState, *, settings: Settings | None = None) -> dict:
    out = run_save_memory(dict(state), settings=settings)
    audit("rag_memory_saved", kind="rag", memory_saved=out.get("memory_saved"), conversation_id=state.get("conversation_id"))
    return {
        **out,
        "rag_audit_payload": build_pipeline_audit({**dict(state), **out}),
    }
