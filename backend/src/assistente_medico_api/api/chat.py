"""Endpoint POST /assistant/chat (SSE ou JSON)."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.schemas.chat import ChatRequest, ChatResponseJson

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
