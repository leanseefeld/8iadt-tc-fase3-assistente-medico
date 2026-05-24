"""Persistência de turnos do chat (conversas e mensagens)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from assistente_medico_api.graph.nodes.generate import GENERATE_SYSTEM_PROMPT
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.models.conversation import Conversation, ConversationMessage
from assistente_medico_api.repositories import conversation_repo, patient_repo


async def resolve_conversation(
    session: AsyncSession,
    *,
    thread_id: str | None,
    doctor_id: str,
    patient_id: str,
) -> tuple[Conversation, str]:
    """
    Resolve ou cria conversa. Retorna (row, thread_id efetivo).
    Sem thread_id: novo UUID e INSERT. Com thread_id: busca ou 404.
    """
    patient = await patient_repo.get_patient_by_id(session, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente nao encontrado")

    tid = (thread_id or "").strip()
    if not tid:
        tid = str(uuid.uuid4())
        row = Conversation(
            id=tid,
            doctor_id=doctor_id,
            patient_id=patient_id,
            system_prompt=GENERATE_SYSTEM_PROMPT,
        )
        await conversation_repo.create_conversation(session, row)
        return row, tid

    existing = await conversation_repo.get_conversation_by_id(session, tid)
    if existing is None:
        raise HTTPException(status_code=404, detail="Conversa nao encontrada")
    if existing.patient_id != patient_id:
        raise HTTPException(
            status_code=400,
            detail="threadId nao corresponde ao paciente informado",
        )
    if existing.doctor_id != doctor_id:
        raise HTTPException(
            status_code=403,
            detail="Conversa pertence a outro medico",
        )
    return existing, tid


async def append_turn(
    session: AsyncSession,
    *,
    conversation: Conversation,
    doctor_message: str,
    final_state: ChatRAGState,
) -> str:
    """Grava par médico + assistente após turno bem-sucedido do grafo. Retorna id da mensagem do assistente."""
    now = datetime.now(UTC)
    doctor_row = ConversationMessage(
        conversation_id=conversation.id,
        author="user",
        content=doctor_message.strip(),
        created_at=now,
    )
    await conversation_repo.create_message(session, doctor_row)

    assistant_content = (final_state.get("answer") or "").strip()
    assistant_row = ConversationMessage(
        conversation_id=conversation.id,
        author="assistant",
        content=assistant_content,
        reasoning_steps=list(final_state.get("reasoning_steps") or []) or None,
        sources=list(final_state.get("sources") or []) or None,
        llm_input=final_state.get("generate_llm_input"),
        llm_output=final_state.get("generate_llm_output"),
        guardrail_status=final_state.get("guardrail_status"),
        created_at=now,
    )
    await conversation_repo.create_message(session, assistant_row)
    await conversation_repo.touch_conversation_updated_at(session, conversation)
    return assistant_row.id
