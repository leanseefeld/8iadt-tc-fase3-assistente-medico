"""Repository: chamadas auxiliares LLM por mensagem do assistente."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from assistente_medico_api.graph.llm_client import AuxLlmTraceEntry
from assistente_medico_api.models.conversation import ConversationMessage
from assistente_medico_api.models.conversation_message_llm_call import ConversationMessageLlmCall


async def bulk_create_llm_calls(
    session: AsyncSession,
    *,
    assistant_message_id: str,
    trace: list[AuxLlmTraceEntry],
) -> list[ConversationMessageLlmCall]:
    rows: list[ConversationMessageLlmCall] = []
    for entry in trace:
        rows.append(
            ConversationMessageLlmCall(
                assistant_message_id=assistant_message_id,
                call_type=str(entry["call_type"]),
                sequence=int(entry.get("sequence", len(rows))),
                model=str(entry.get("model") or ""),
                llm_input=list(entry["llm_input"]),
                llm_output=str(entry["llm_output"]),
            )
        )
    for row in rows:
        session.add(row)
    if rows:
        await session.flush()
    return rows


async def list_by_assistant_message_id(
    session: AsyncSession,
    assistant_message_id: str,
) -> list[ConversationMessageLlmCall]:
    statement = (
        select(ConversationMessageLlmCall)
        .where(ConversationMessageLlmCall.assistant_message_id == assistant_message_id)
        .order_by(col(ConversationMessageLlmCall.sequence).asc())
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def list_all_llm_interactions_for_message(
    session: AsyncSession,
    message_id: str,
) -> list[dict]:
    """
    Retorna todas as interações LLM correlacionadas ao message_id do assistente:
    par generate em conversation_messages + linhas auxiliares ordenadas por sequence.
    """
    message = (
        await session.execute(
            select(ConversationMessage).where(ConversationMessage.id == message_id)
        )
    ).scalar_one_or_none()
    if message is None:
        return []

    out: list[dict] = []
    if message.llm_input is not None and message.llm_output is not None:
        out.append(
            {
                "call_type": "generate",
                "sequence": -1,
                "model": None,
                "llm_input": message.llm_input,
                "llm_output": message.llm_output,
                "source": "conversation_messages",
            }
        )

    aux_rows = await list_by_assistant_message_id(session, message_id)
    for row in aux_rows:
        out.append(
            {
                "call_type": row.call_type,
                "sequence": row.sequence,
                "model": row.model,
                "llm_input": row.llm_input,
                "llm_output": row.llm_output,
                "source": "conversation_message_llm_calls",
                "id": row.id,
            }
        )

    out.sort(key=lambda item: (item["sequence"], item["call_type"]))
    return out
