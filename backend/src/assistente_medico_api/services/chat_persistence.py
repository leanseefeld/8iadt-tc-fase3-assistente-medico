"""Persistência de turnos do chat (conversas e mensagens)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes.generate import GENERATE_SYSTEM_PROMPT
from assistente_medico_api.graph.state import CHAT_HISTORY_MAX_ITEMS, ChatRAGState, ChatHistoryTurnState
from assistente_medico_api.services.llm_interaction_log import persist_aux_trace
from assistente_medico_api.models.conversation import Conversation, ConversationMessage
from assistente_medico_api.repositories import conversation_repo, patient_repo
from assistente_medico_api.schemas.chat import (
    ConversationArchiveResponse,
    ConversationListResponse,
    ConversationMessageResponse,
    ConversationMessagesResponse,
    ConversationSummary,
)


def _ensure_not_archived(conversation: Conversation) -> None:
    if conversation.archived_at is not None:
        raise HTTPException(
            status_code=410,
            detail="Conversa arquivada e inacessivel",
        )


def _ensure_doctor_owns(conversation: Conversation, doctor_id: str) -> None:
    if conversation.doctor_id != doctor_id:
        raise HTTPException(
            status_code=403,
            detail="Conversa pertence a outro medico",
        )


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
    _ensure_doctor_owns(existing, doctor_id)
    _ensure_not_archived(existing)
    return existing, tid


async def append_turn(
    session: AsyncSession,
    *,
    conversation: Conversation,
    doctor_message: str,
    final_state: ChatRAGState,
    settings: Settings,
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
    await persist_aux_trace(
        session,
        assistant_message_id=assistant_row.id,
        trace=final_state.get("aux_llm_trace"),
        settings=settings,
    )
    await conversation_repo.touch_conversation_updated_at(session, conversation)
    return assistant_row.id


async def list_patient_conversations(
    session: AsyncSession,
    *,
    patient_id: str,
    doctor_id: str,
) -> ConversationListResponse:
    """Lista conversas não arquivadas do médico para o paciente, com preview."""
    patient = await patient_repo.get_patient_by_id(session, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente nao encontrado")

    rows = await conversation_repo.list_conversations_by_patient_and_doctor(
        session,
        patient_id=patient_id,
        doctor_id=doctor_id,
    )
    previews = await conversation_repo.fetch_first_user_message_previews(
        session,
        [row.id for row in rows],
    )
    summaries = [
        ConversationSummary(
            id=row.id,
            patient_id=row.patient_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            preview=previews.get(row.id),
        )
        for row in rows
    ]
    return ConversationListResponse(conversations=summaries)


async def get_conversation_messages(
    session: AsyncSession,
    *,
    conversation_id: str,
    doctor_id: str,
) -> ConversationMessagesResponse:
    """Retorna mensagens completas se o médico for dono e a conversa estiver ativa."""
    conversation = await conversation_repo.get_conversation_by_id(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversa nao encontrada")
    _ensure_doctor_owns(conversation, doctor_id)
    _ensure_not_archived(conversation)

    rows = await conversation_repo.list_messages_by_conversation(session, conversation_id)
    messages = [
        ConversationMessageResponse(
            id=row.id,
            author=row.author,  # type: ignore[arg-type]
            content=row.content,
            sources=list(row.sources or []) or None,
            reasoning_steps=list(row.reasoning_steps or []) or None,
            feedback_rating=row.feedback_rating,  # type: ignore[arg-type]
            created_at=row.created_at,
        )
        for row in rows
    ]
    return ConversationMessagesResponse(
        conversation_id=conversation_id,
        patient_id=conversation.patient_id,
        messages=messages,
    )


async def archive_conversation_for_doctor(
    session: AsyncSession,
    *,
    conversation_id: str,
    doctor_id: str,
) -> ConversationArchiveResponse:
    """Arquiva conversa; idempotência rejeitada com 409."""
    conversation = await conversation_repo.get_conversation_by_id(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversa nao encontrada")
    _ensure_doctor_owns(conversation, doctor_id)
    if conversation.archived_at is not None:
        raise HTTPException(status_code=409, detail="Conversa ja arquivada")

    updated = await conversation_repo.archive_conversation(
        session,
        conversation,
        archived_by=doctor_id,
    )
    return ConversationArchiveResponse(
        id=updated.id,
        archived_at=updated.archived_at,  # type: ignore[arg-type]
        archived_by=updated.archived_by,  # type: ignore[arg-type]
    )


async def build_chat_history_from_db(
    session: AsyncSession,
    conversation_id: str,
) -> list[ChatHistoryTurnState]:
    """Converte mensagens persistidas em chat_history para retomada do grafo."""
    rows = await conversation_repo.list_messages_by_conversation(session, conversation_id)
    history: list[ChatHistoryTurnState] = []
    for row in rows:
        if row.author not in ("user", "assistant"):
            continue
        content = row.content.strip()
        if not content:
            continue
        history.append({"role": row.author, "content": content})  # type: ignore[typeddict-item]
    if len(history) > CHAT_HISTORY_MAX_ITEMS:
        history = history[-CHAT_HISTORY_MAX_ITEMS:]
    return history
