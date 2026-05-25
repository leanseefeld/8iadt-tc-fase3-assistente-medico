"""Persistência de chamadas auxiliares ao LLM de chat por turno."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.llm_client import AuxLlmTraceEntry
from assistente_medico_api.repositories import llm_interaction_log_repo


async def persist_aux_trace(
    session: AsyncSession,
    *,
    assistant_message_id: str,
    trace: list[AuxLlmTraceEntry] | None,
    settings: Settings,
) -> None:
    """Grava o buffer do grafo na tabela filha quando o flag estiver ativo."""
    if not settings.llm_interaction_log_enabled:
        return
    entries = list(trace or [])
    if not entries:
        return
    await llm_interaction_log_repo.bulk_create_llm_calls(
        session,
        assistant_message_id=assistant_message_id,
        trace=entries,
    )
