"""Endpoint POST /assistant/chat (SSE ou JSON)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from assistente_medico_api.graph.state import CHAT_HISTORY_MAX_ITEMS, ChatRAGState
from assistente_medico_api.deps import get_session
from assistente_medico_api.services import chat_persistence
from assistente_medico_api.repositories import conversation_repo, patient_repo
from assistente_medico_api.schemas.chat import (
    ChatHistoryTurnModel,
    ChatRequest,
    ChatResponseJson,
    ConversationArchiveResponse,
    ConversationListResponse,
    ConversationMessagesResponse,
    DecisionFlowMeta,
    DecisionFlowRequest,
    DecisionFlowResponse,
    MessageFeedbackPatchRequest,
    MessageFeedbackPatchResponse,
)
from assistente_medico_api.graph.state import ChatHistoryTurnState
from assistente_medico_api.services.protocol_map import get_protocol_for_cid
from assistente_medico_api.observability.audit import audit, truncate
from assistente_medico_api.observability.context import (
    get_user_id,
    set_patient_id,
    set_thread_id,
)
from assistente_medico_api.observability.clinical_audit_jsonl import ClinicalAuditAction, clinical_audit

router = APIRouter(prefix="/assistant", tags=["assistant"])


def _normalize_message_history(
    body: ChatRequest,
) -> list[ChatHistoryTurnState]:
    """
    Converte o histórico do cliente no formato do grafo, corta a janela e remove
    conteúdo vazio (teto alinhado a CHAT_HISTORY_MAX_ITEMS e ao schema).
    """
    raw: list[ChatHistoryTurnModel] = list(body.message_history or [])
    if not raw:
        return []
    if len(raw) > CHAT_HISTORY_MAX_ITEMS:
        raw = raw[-CHAT_HISTORY_MAX_ITEMS:]
    return [
        {
            "role": turn.role,
            "content": turn.content.strip(),
        }
        for turn in raw
        if turn.content.strip()
    ]


async def _invoke_payload_and_config(
    request: Request,
    body: ChatRequest,
    graph,
    thread_id: str,
    session: AsyncSession,
    *,
    is_resumed_thread: bool,
) -> tuple[dict, dict, str]:
    """
    Monta o update de estado e o RunnableConfig (thread_id) para o grafo com checkpointer.

    Se já existe chat_history no checkpoint, não reenvia `chat_history` no update (merge).
    Caso contrário, semeia a partir do DB (thread retomado) ou `messageHistory` no corpo.
    """
    tid = thread_id
    config: dict = {"configurable": {"thread_id": tid}}
    snap = await graph.aget_state(config)
    vals = snap.values or {}
    has_persisted_history = bool(vals.get("chat_history"))

    payload: dict = {
        "query": body.message.strip(),
        "patient_id": body.patient_id,
        "retrieved_docs": [],
        "sources": [],
        "reasoning_steps": [],
        "answer": "",
        "retrieval_query": "",
        "patient_context": "",
    }
    if not has_persisted_history:
        if is_resumed_thread:
            payload["chat_history"] = await chat_persistence.build_chat_history_from_db(
                session,
                tid,
            )
        else:
            payload["chat_history"] = _normalize_message_history(body)

    registry = getattr(request.app.state, "patient_threads_registry", None)
    if registry is not None and body.patient_id:
        registry.setdefault(body.patient_id, set()).add(tid)

    return payload, config, tid


def _get_graph(request: Request):
    """Lê store/settings/graph do app.state; retorna 503 se não inicializado."""
    graph = getattr(request.app.state, "chat_graph", None)
    if graph is None:
        raise HTTPException(
            status_code=503,
            detail="Serviço indisponível: inicialização incompleta.",
        )
    return graph


def _flow_ts(base: datetime, offset_seconds: int) -> str:
    return (base + timedelta(seconds=offset_seconds)).strftime("%H:%M:%S")


def _require_doctor_id() -> str:
    """Exige identificação do médico (header X-User-Id) para persistir conversas."""
    doctor_id = (get_user_id() or "").strip()
    if not doctor_id:
        raise HTTPException(
            status_code=400,
            detail="Header X-User-Id obrigatorio para o chat.",
        )
    return doctor_id


@router.post("/chat")
async def post_chat(
    request: Request,
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
    accept: Annotated[str | None, Header(alias="Accept")] = None,
):
    """Chat RAG: SSE com graph.astream_events(); JSON de fallback com graph.invoke()."""
    graph = _get_graph(request)
    doctor_id = _require_doctor_id()
    conversation, thread_id = await chat_persistence.resolve_conversation(
        session,
        thread_id=body.thread_id,
        doctor_id=doctor_id,
        patient_id=body.patient_id,
    )
    is_resumed_thread = bool((body.thread_id or "").strip())
    initial, config, thread_id = await _invoke_payload_and_config(
        request,
        body,
        graph,
        thread_id,
        session,
        is_resumed_thread=is_resumed_thread,
    )
    wants_stream = bool(accept and "text/event-stream" in accept.lower())

    set_thread_id(thread_id)
    set_patient_id(body.patient_id or None)
    t_started = time.perf_counter()

    audit(
        "chat_request_received",
        kind="chat",
        thread_id=thread_id,
        patient_id=(body.patient_id or None),
        query_snippet=truncate(body.message),
        accept=(accept or ""),
        stream=wants_stream,
    )
    clinical_audit(
        ClinicalAuditAction.CONVERSA_ASSISTENTE_SOLICITADA,
        patient_id=body.patient_id,
        descricao="Pedido de conversa com o assistente (chat RAG).",
        detalhes={
            "thread_id": thread_id,
            "stream": wants_stream,
            "accept": truncate(accept or "", n=120),
            "pergunta_truncada": truncate(body.message, n=400),
        },
    )

    # --- Caminho JSON: usa API async (grafo contém nós async) ---
    if not wants_stream:
        try:
            final: ChatRAGState = await graph.ainvoke(initial, config)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Falha ao executar o assistente: {exc!s}",
            ) from exc
        assistant_message_id = await chat_persistence.append_turn(
            session,
            conversation=conversation,
            doctor_message=body.message,
            final_state=final,
        )
        await session.commit()

        lat = round((time.perf_counter() - t_started) * 1000, 2)
        audit(
            "chat_response_done",
            kind="chat",
            latency_ms=lat,
            thread_id=thread_id,
            patient_id=(body.patient_id or None),
            mode="json",
            guardrail_status=final.get("guardrail_status"),
            tokens_streamed=0,
        )
        clinical_audit(
            ClinicalAuditAction.CONVERSA_ASSISTENTE_FINALIZADA,
            patient_id=body.patient_id,
            descricao="Resposta do assistente entregue (modo JSON).",
            detalhes={
                "thread_id": thread_id,
                "modo": "json",
                "latency_ms": lat,
                "tokens_streamed": 0,
                "guardrail_status": final.get("guardrail_status"),
            },
        )
        return ChatResponseJson(
            text=final.get("answer") or "",
            sources=list(final.get("sources") or []),
            reasoning=list(final.get("reasoning_steps") or []),
            thread_id=thread_id,
            message_id=assistant_message_id,
            audit_id=final.get("audit_id") or None,
            guardrail_status=final.get("guardrail_status") or None,
            guardrail_reason=final.get("guardrail_reason") or None,
        )

    # --- Caminho SSE: astream_events emite on_chat_model_stream por token ---
    async def event_gen():
        tokens_streamed = 0
        guard_status: str | None = None

        def finalize_audit() -> None:
            lat = round((time.perf_counter() - t_started) * 1000, 2)
            audit(
                "chat_response_done",
                kind="chat",
                latency_ms=lat,
                thread_id=thread_id,
                patient_id=(body.patient_id or None),
                mode="sse",
                guardrail_status=guard_status,
                tokens_streamed=tokens_streamed,
            )
            clinical_audit(
                ClinicalAuditAction.CONVERSA_ASSISTENTE_FINALIZADA,
                patient_id=body.patient_id,
                descricao="Resposta do assistente entregue (modo SSE).",
                detalhes={
                    "thread_id": thread_id,
                    "modo": "sse",
                    "latency_ms": lat,
                    "tokens_streamed": tokens_streamed,
                    "guardrail_status": guard_status,
                },
            )

        try:
            async for event in graph.astream_events(initial, config, version="v2"):
                kind = event["event"]

                # Retrieve terminou → envia metadados antes dos tokens.
                if kind == "on_chain_end" and event.get("name") == "retrieve":
                    output = event["data"].get("output") or {}
                    yield {
                        "event": "sources",
                        "data": json.dumps({"sources": output.get("sources") or []}),
                    }
                    yield {
                        "event": "reasoning",
                        "data": json.dumps({"steps": output.get("reasoning_steps") or []}),
                    }

                # Guardrail terminou → envia status e resposta final.
                # Se o status não for "safe", o frontend substitui o texto
                # acumulado pelos tokens já exibidos (AVISO appenda disclaimer;
                # BLOQUEAR/regenerated substitui por mensagem segura).
                elif kind == "on_chain_end" and event.get("name") == "guardrail":
                    output = event["data"].get("output") or {}
                    guard_status = output.get("guardrail_status")
                    yield {
                        "event": "guardrail",
                        "data": json.dumps(
                            {
                                "status": output.get("guardrail_status"),
                                "reason": output.get("guardrail_reason"),
                                "answer": output.get("answer"),
                                "auditId": output.get("audit_id"),
                            }
                        ),
                    }

                # Token do LLM dentro do nó generate — filtra por nó para não vazar
                # tokens internos do guardrail (classificador, regeneração).
                elif kind == "on_chat_model_stream" and event.get("metadata", {}).get("langgraph_node") == "generate":
                    chunk = event["data"].get("chunk")
                    piece = getattr(chunk, "content", None) if chunk else None
                    if isinstance(piece, list):
                        piece = "".join(str(p) for p in piece)
                    if piece:
                        tokens_streamed += 1
                        yield {
                            "event": "token",
                            "data": json.dumps({"content": str(piece)}),
                        }

            snap = await graph.aget_state(config)
            final_sse: ChatRAGState = snap.values or {}
            assistant_message_id = await chat_persistence.append_turn(
                session,
                conversation=conversation,
                doctor_message=body.message,
                final_state=final_sse,
            )
            await session.commit()

            yield {
                "event": "done",
                "data": json.dumps(
                    {"threadId": thread_id, "messageId": assistant_message_id}
                ),
            }

        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({"detail": str(exc)}),
            }
            finalize_audit()
            return

        finalize_audit()

    return EventSourceResponse(event_gen())


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    patient_id: Annotated[str, Query(alias="patientId")],
    session: AsyncSession = Depends(get_session),
) -> ConversationListResponse:
    """Lista conversas não arquivadas do médico logado para o paciente."""
    doctor_id = _require_doctor_id()
    result = await chat_persistence.list_patient_conversations(
        session,
        patient_id=patient_id,
        doctor_id=doctor_id,
    )
    return result


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationMessagesResponse,
)
async def get_conversation_messages(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
) -> ConversationMessagesResponse:
    """Retorna mensagens persistidas para hidratar a UI."""
    doctor_id = _require_doctor_id()
    return await chat_persistence.get_conversation_messages(
        session,
        conversation_id=conversation_id,
        doctor_id=doctor_id,
    )


@router.patch(
    "/conversations/{conversation_id}/archive",
    response_model=ConversationArchiveResponse,
)
async def archive_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
) -> ConversationArchiveResponse:
    """Arquiva conversa (permanece no banco, inacessível na UI)."""
    doctor_id = _require_doctor_id()
    result = await chat_persistence.archive_conversation_for_doctor(
        session,
        conversation_id=conversation_id,
        doctor_id=doctor_id,
    )
    await session.commit()
    return result


@router.patch(
    "/conversations/{conversation_id}/messages/{message_id}",
    response_model=MessageFeedbackPatchResponse,
)
async def patch_message_feedback(
    conversation_id: str,
    message_id: str,
    body: MessageFeedbackPatchRequest,
    session: AsyncSession = Depends(get_session),
) -> MessageFeedbackPatchResponse:
    """Avalia ou remove avaliação de uma mensagem do assistente."""
    doctor_id = _require_doctor_id()
    conversation = await conversation_repo.get_conversation_by_id(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversa nao encontrada")
    if conversation.doctor_id != doctor_id:
        raise HTTPException(
            status_code=403,
            detail="Conversa pertence a outro medico",
        )
    if conversation.archived_at is not None:
        raise HTTPException(
            status_code=410,
            detail="Conversa arquivada e inacessivel",
        )

    message = await conversation_repo.get_message_by_id(session, message_id)
    if message is None or message.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Mensagem nao encontrada")
    if message.author != "assistant":
        raise HTTPException(
            status_code=400,
            detail="Apenas mensagens do assistente podem ser avaliadas",
        )

    updated = await conversation_repo.set_message_feedback(
        session,
        message,
        body.feedback_rating,
    )
    await session.commit()
    return MessageFeedbackPatchResponse(
        message_id=updated.id,
        feedback_rating=updated.feedback_rating,  # type: ignore[arg-type]
    )


@router.post("/decision-flow", response_model=DecisionFlowResponse)
async def post_decision_flow(
    body: DecisionFlowRequest,
    session: AsyncSession = Depends(get_session),
) -> DecisionFlowResponse:
    patient = await patient_repo.get_patient_by_id(session, body.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente nao encontrado")

    t0 = time.perf_counter()
    set_patient_id(body.patient_id)
    audit(
        "decision_flow_run",
        kind="chat",
        patient_id=body.patient_id,
    )

    exams = await patient_repo.list_exams(session, patient.id)
    items = await patient_repo.list_suggested_items(session, patient.id)
    proto = get_protocol_for_cid(patient.cid_code)

    meta = DecisionFlowMeta(
        sepsisCritical=patient.cid_code == "A41.9",
        pharmacyInteraction=(
            patient.cid_code == "T81.4" and bool(proto.drug_interaction_alert)
        ),
    )

    now = datetime.now(UTC)
    exam_summary = ", ".join(e.name.split(" ")[0] for e in exams) if exams else "nenhum"

    lines: list[str] = [
        (
            f"[{_flow_ts(now, 0)}] Triagem: dados do paciente carregados - "
            f"{patient.cid_code}, {patient.name}, {patient.age} anos"
        ),
        f"[{_flow_ts(now, 1)}] Consultando protocolo: {proto.protocol_ref}",
        f"[{_flow_ts(now, 2)}] Exames identificados: {exam_summary}",
        (
            f"[{_flow_ts(now, 3)}] Acoes sugeridas geradas: {len(items)} itens - "
            "aguarda aprovacao medica"
        ),
    ]
    if meta.sepsis_critical:
        lines.append("Caso critico detectado - alerta imediato para equipe medica")
    if meta.pharmacy_interaction:
        lines.append(
            "Possivel interacao medicamentosa detectada - encaminhado para farmacia"
        )
    lines.append(f"[{_flow_ts(now, 4)}] Alerta enviado: equipes notificadas conforme regras")
    lines.append(f"[{_flow_ts(now, 5)}] Fluxo concluido")

    flow_latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    audit(
        "decision_flow_done",
        kind="chat",
        latency_ms=flow_latency_ms,
        patient_id=body.patient_id,
    )

    clinical_audit(
        ClinicalAuditAction.EXECUCAO_FLUXO_DECISAO,
        patient_id=body.patient_id,
        patient_name=patient.name,
        descricao=f"Fluxo de decisão executado para {patient.name} (protótipo).",
        detalhes={
            "latency_ms": flow_latency_ms,
            "protocolo": proto.protocol_ref,
            "exames_carregados": len(exams),
            "acoes_sugeridas": len(items),
            "alerta_sepse_meta": meta.sepsis_critical,
            "alerta_farmacia_meta": meta.pharmacy_interaction,
        },
    )

    return DecisionFlowResponse(lines=lines, meta=meta)
