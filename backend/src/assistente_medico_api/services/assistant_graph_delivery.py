"""Execução compartilhada do grafo RAG do chat (JSON e SSE)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sse_starlette.sse import EventSourceResponse

from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.schemas.chat import ChatResponseJson


@dataclass
class GraphStreamContext:
    """Estado acumulado durante streaming SSE do grafo."""

    final_state: dict[str, Any] = field(default_factory=dict)
    tokens_streamed: int = 0
    guardrail_status: str | None = None


async def invoke_assistant_graph(
    graph,
    initial: dict,
    config: dict,
) -> ChatRAGState:
    """Executa o grafo e converte falhas em HTTP 503."""
    try:
        return await graph.ainvoke(initial, config)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Falha ao executar o assistente: {exc!s}",
        ) from exc


def assistant_response_json(
    final_state: ChatRAGState | dict,
    *,
    thread_id: str,
    message_id: str,
) -> ChatResponseJson:
    """Monta resposta JSON alinhada ao contrato do frontend."""
    return ChatResponseJson(
        text=final_state.get("answer") or "",
        sources=list(final_state.get("sources") or []),
        reasoning=list(final_state.get("reasoning_steps") or []),
        thread_id=thread_id,
        message_id=message_id,
        audit_id=final_state.get("audit_id") or None,
        guardrail_status=final_state.get("guardrail_status") or None,
        guardrail_reason=final_state.get("guardrail_reason") or None,
    )


def assistant_final_sse_payload(final_state: dict, *, thread_id: str) -> dict:
    """Payload do evento SSE ``final``."""
    return {
        "text": final_state.get("answer") or "",
        "sources": list(final_state.get("sources") or []),
        "reasoning": list(final_state.get("reasoning_steps") or []),
        "threadId": thread_id,
        "auditId": final_state.get("audit_id"),
        "guardrailStatus": final_state.get("guardrail_status"),
        "guardrailReason": final_state.get("guardrail_reason"),
    }


async def iter_assistant_graph_sse(
    graph,
    initial: dict,
    config: dict,
    ctx: GraphStreamContext,
) -> AsyncIterator[dict[str, str]]:
    """
    Emite eventos SSE intermediários (sources, reasoning, guardrail, token).

    O estado final fica em ``ctx.final_state``.
    """
    async for event in graph.astream_events(initial, config, version="v2"):
        kind = event["event"]

        if kind == "on_chain_end":
            output = event["data"].get("output") or {}
            if isinstance(output, dict):
                ctx.final_state.update(output)

        if kind == "on_chain_end" and event.get("name") in ("rerank", "specialized_search"):
            output = event["data"].get("output") or {}
            yield {
                "event": "sources",
                "data": json.dumps(
                    {
                        "sources": list(
                            ctx.final_state.get("sources") or output.get("sources") or []
                        )
                    }
                ),
            }
            yield {
                "event": "reasoning",
                "data": json.dumps(
                    {
                        "steps": list(
                            ctx.final_state.get("reasoning_steps")
                            or output.get("reasoning_steps")
                            or []
                        )
                    }
                ),
            }

        elif kind == "on_chain_end" and event.get("name") == "guardrail":
            output = event["data"].get("output") or {}
            ctx.guardrail_status = ctx.final_state.get("guardrail_status") or output.get(
                "guardrail_status"
            )
            yield {
                "event": "guardrail",
                "data": json.dumps(
                    {
                        "status": ctx.final_state.get("guardrail_status"),
                        "reason": ctx.final_state.get("guardrail_reason"),
                        "answer": ctx.final_state.get("answer"),
                        "auditId": ctx.final_state.get("audit_id"),
                    }
                ),
            }

        elif (
            kind == "on_chat_model_stream"
            and event.get("metadata", {}).get("langgraph_node") == "generate"
        ):
            chunk = event["data"].get("chunk")
            piece = getattr(chunk, "content", None) if chunk else None
            if isinstance(piece, list):
                piece = "".join(str(p) for p in piece)
            if piece:
                ctx.tokens_streamed += 1
                yield {
                    "event": "token",
                    "data": json.dumps({"content": str(piece)}),
                }


def assistant_graph_sse_response(
    *,
    graph,
    initial: dict,
    config: dict,
    thread_id: str,
    session,
    persist: Callable[[dict], Awaitable[str]],
    finalize: Callable[[GraphStreamContext], None],
) -> EventSourceResponse:
    """Resposta SSE completa: stream, persistência, eventos final/done e auditoria."""

    async def event_gen():
        ctx = GraphStreamContext()
        try:
            async for sse in iter_assistant_graph_sse(graph, initial, config, ctx):
                yield sse

            message_id = await persist(ctx.final_state)
            await session.commit()

            yield {
                "event": "final",
                "data": json.dumps(
                    assistant_final_sse_payload(ctx.final_state, thread_id=thread_id)
                ),
            }
            yield {
                "event": "done",
                "data": json.dumps({"threadId": thread_id, "messageId": message_id}),
            }
        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({"detail": str(exc)}),
            }
            finalize(ctx)
            return

        finalize(ctx)

    return EventSourceResponse(event_gen())
