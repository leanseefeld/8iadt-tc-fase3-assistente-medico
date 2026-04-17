"""Endpoint POST /assistant/chat (SSE ou JSON)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.deps import get_session
from assistente_medico_api.repositories import patient_repo
from assistente_medico_api.schemas.chat import (
    ChatRequest,
    ChatResponseJson,
    DecisionFlowMeta,
    DecisionFlowRequest,
    DecisionFlowResponse,
)
from assistente_medico_api.services.protocol_map import get_protocol_for_cid

router = APIRouter(prefix="/assistant", tags=["assistant"])


def _initial_state(body: ChatRequest) -> ChatRAGState:
    return {
        "query": body.message.strip(),
        "patient_id": body.patient_id,
        "retrieved_docs": [],
        "sources": [],
        "reasoning_steps": [],
        "answer": "",
    }


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


@router.post("/chat")
async def post_chat(
    request: Request,
    body: ChatRequest,
    accept: Annotated[str | None, Header(alias="Accept")] = None,
):
    """Chat RAG: SSE com graph.astream_events(); JSON de fallback com graph.invoke()."""
    graph = _get_graph(request)
    initial = _initial_state(body)
    wants_stream = bool(accept and "text/event-stream" in accept.lower())

    # --- Caminho JSON: usa API async (grafo contém nós async) ---
    if not wants_stream:
        try:
            final: ChatRAGState = await graph.ainvoke(initial)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Falha ao executar o assistente: {exc!s}",
            ) from exc
        return ChatResponseJson(
            text=final.get("answer") or "",
            sources=list(final.get("sources") or []),
            reasoning=list(final.get("reasoning_steps") or []),
        )

    # --- Caminho SSE: astream_events emite on_chat_model_stream por token ---
    async def event_gen():
        try:
            async for event in graph.astream_events(initial, version="v2"):
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

                # Token do LLM dentro do nó generate.
                elif kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    piece = getattr(chunk, "content", None) if chunk else None
                    if isinstance(piece, list):
                        piece = "".join(str(p) for p in piece)
                    if piece:
                        yield {
                            "event": "token",
                            "data": json.dumps({"content": str(piece)}),
                        }

            yield {"event": "done", "data": "{}"}

        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({"detail": str(exc)}),
            }
            return

    return EventSourceResponse(event_gen())


@router.post("/decision-flow", response_model=DecisionFlowResponse)
async def post_decision_flow(
    body: DecisionFlowRequest,
    session: AsyncSession = Depends(get_session),
) -> DecisionFlowResponse:
    patient = await patient_repo.get_patient_by_id(session, body.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente nao encontrado")

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

    return DecisionFlowResponse(lines=lines, meta=meta)
