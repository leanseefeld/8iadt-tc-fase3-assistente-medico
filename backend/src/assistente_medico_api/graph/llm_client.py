"""Cliente Ollama compartilhado e invocações rastreadas para SFT."""

from __future__ import annotations

from typing import Any

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from assistente_medico_api.config import Settings

# Entrada de trace em memória durante o turno do grafo (antes do assistant_message_id).
AuxLlmTraceEntry = dict[str, Any]


def serialize_messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
    """Serializa mensagens LangChain para persistência JSON (SFT/auditoria)."""
    out: list[dict[str, str]] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            role = "system"
        elif isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        else:
            role = getattr(msg, "type", "unknown")
        content = msg.content
        if isinstance(content, list):
            content = "".join(str(p) for p in content)
        out.append({"role": role, "content": str(content or "")})
    return out


def _message_content(result: BaseMessage) -> str:
    raw = getattr(result, "content", None) or ""
    if isinstance(raw, list):
        return "".join(str(p) for p in raw)
    return str(raw)


def build_llm(settings: Settings, *, temperature: float = 0.2) -> ChatOllama:
    """Cria o cliente Ollama para MEDICO_OLLAMA_CHAT_MODEL."""
    timeout = httpx.Timeout(settings.llm_stream_timeout_s, connect=10.0)
    return ChatOllama(
        model=settings.ollama_chat_model,
        base_url=settings.ollama_base_url,
        temperature=temperature,
        async_client_kwargs={"timeout": timeout},
        client_kwargs={"timeout": timeout},
    )


def append_aux_trace_entry(
    trace: list[AuxLlmTraceEntry],
    *,
    call_type: str,
    messages: list[BaseMessage],
    result_content: str,
    settings: Settings,
) -> None:
    """Acrescenta entrada ao buffer do turno (sem persistir)."""
    if not settings.llm_interaction_log_enabled:
        return
    trace.append(
        {
            "call_type": call_type,
            "llm_input": serialize_messages(messages),
            "llm_output": result_content,
            "model": settings.ollama_chat_model,
            "sequence": len(trace),
        }
    )


async def tracked_ainvoke(
    llm: ChatOllama,
    messages: list[BaseMessage],
    *,
    call_type: str,
    trace: list[AuxLlmTraceEntry],
    settings: Settings,
) -> BaseMessage:
    """Invoca o modelo e registra entrada/saída no trace auxiliar quando habilitado."""
    result = await llm.ainvoke(messages)
    append_aux_trace_entry(
        trace,
        call_type=call_type,
        messages=messages,
        result_content=_message_content(result),
        settings=settings,
    )
    return result
