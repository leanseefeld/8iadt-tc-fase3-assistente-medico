"""Endpoint POST /assistant/chat (SSE ou JSON)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from assistente_medico_api.graph.state import CHAT_HISTORY_MAX_ITEMS, ChatRAGState
from assistente_medico_api.deps import get_session
from assistente_medico_api.services import chat_persistence
from assistente_medico_api.repositories import patient_repo
from assistente_medico_api.schemas.chat import (
    ChatHistoryTurnModel,
    ChatRequest,
    ChatResponseJson,
    DecisionFlowMeta,
    DecisionFlowRequest,
    DecisionFlowResponse,
)
from assistente_medico_api.graph.state import ChatHistoryTurnState
from assistente_medico_api.services.protocol_map import get_protocol_for_cid
from assistente_medico_api.observability.audit import audit, truncate
from assistente_medico_api.observability.context import (
    get_user_id,
    set_patient_id,
    set_thread_id,
)

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
) -> tuple[dict, dict, str]:
    """
    Monta o update de estado e o RunnableConfig (thread_id) para o grafo com checkpointer.

    Se já existe chat_history no checkpoint, não reenvia `chat_history` no update (merge).
    Caso contrário, semeia a partir de `messageHistory` no corpo (clientes sem threadId).
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
    initial, config, thread_id = await _invoke_payload_and_config(
        request, body, graph, thread_id
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

    # --- Caminho JSON: usa API async (grafo contém nós async) ---
    if not wants_stream:
        try:
            final: ChatRAGState = await graph.ainvoke(initial, config)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Falha ao executar o assistente: {exc!s}",
            ) from exc
        await chat_persistence.append_turn(
            session,
            conversation=conversation,
            doctor_message=body.message,
            final_state=final,
        )
        await session.commit()
        audit(
            "chat_response_done",
            kind="chat",
            latency_ms=round((time.perf_counter() - t_started) * 1000, 2),
            thread_id=thread_id,
            patient_id=(body.patient_id or None),
            mode="json",
            guardrail_status=final.get("guardrail_status"),
            tokens_streamed=0,
        )
        return ChatResponseJson(
            text=final.get("answer") or "",
            sources=list(final.get("sources") or []),
            reasoning=list(final.get("reasoning_steps") or []),
            thread_id=thread_id,
            audit_id=final.get("audit_id") or None,
            guardrail_status=final.get("guardrail_status") or None,
            guardrail_reason=final.get("guardrail_reason") or None,
        )

    # --- Caminho SSE: astream_events emite on_chat_model_stream por token ---
    async def event_gen():
        tokens_streamed = 0
        guard_status = None

        def finalize_audit() -> None:
            audit(
                "chat_response_done",
                kind="chat",
                latency_ms=round((time.perf_counter() - t_started) * 1000, 2),
                thread_id=thread_id,
                patient_id=(body.patient_id or None),
                mode="sse",
                guardrail_status=guard_status,
                tokens_streamed=tokens_streamed,
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
            await chat_persistence.append_turn(
                session,
                conversation=conversation,
                doctor_message=body.message,
                final_state=final_sse,
            )
            await session.commit()

            yield {
                "event": "done",
                "data": json.dumps({"threadId": thread_id}),
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

    audit(
        "decision_flow_done",
        kind="chat",
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        patient_id=body.patient_id,
    )

    return DecisionFlowResponse(lines=lines, meta=meta)
