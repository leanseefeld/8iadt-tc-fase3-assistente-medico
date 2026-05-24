"""LangGraph node: load conversation memory."""

from __future__ import annotations

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit
from assistente_medico_api.services.rag_pipeline_service import run_load_memory


def load_memory_node(state: ChatRAGState, *, settings: Settings | None = None) -> dict:
    out = run_load_memory(dict(state), settings=settings)
    audit("rag_memory_loaded", kind="rag", memory_result=out.get("memory_result") or {})
    return out
