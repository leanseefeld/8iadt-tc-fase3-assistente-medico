"""Invalidação de cache de contexto clínico do paciente nos threads LangGraph."""

from __future__ import annotations

from typing import Any


async def invalidate_patient_context(app_state: Any, patient_id: str) -> None:
    """
    Limpa patient_context nos checkpoints de todos os threads do paciente.

    Falhas silenciosas (checkpoint expirado/inexistente) são ignoradas.
    """
    registry = getattr(app_state, "patient_threads_registry", None) or {}
    graph = getattr(app_state, "chat_graph", None)
    if not graph or not patient_id:
        return

    thread_ids = list(registry.get(patient_id, set()))
    for tid in thread_ids:
        try:
            config = {"configurable": {"thread_id": tid}}
            snap = await graph.aget_state(config)
            if snap.values:
                await graph.aupdate_state(config, {"patient_context": ""})
        except Exception:
            pass
