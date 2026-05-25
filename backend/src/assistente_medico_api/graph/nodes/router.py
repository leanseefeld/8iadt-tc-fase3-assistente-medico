"""Aresta de decisão do grafo: define se a pergunta segue para RAG ou resposta direta."""

from __future__ import annotations

import time

from langchain_core.messages import HumanMessage, SystemMessage

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.llm_client import AuxLlmTraceEntry, build_llm, tracked_ainvoke
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate

_ROUTER_SYSTEM = """\
Você é uma aresta de decisão para um assistente clínico.
Classifique a pergunta em apenas uma das opções:
- "direct" quando a pergunta for saudação, conversa genérica ou resposta sem busca documental.
- "rag" quando a pergunta exigir consulta a PCDTs, diretrizes, critérios clínicos, CID, tratamento ou evidência.

Responda somente em JSON puro no formato:
{"route":"direct"|"rag","reason":"<motivo curto>","confidence":0.0}
"""


def _heuristic_router(query: str) -> dict[str, object]:
    text = query.strip().lower()
    if not text:
        return {"route": "direct", "reason": "pergunta vazia", "confidence": 1.0}
    if text in {"oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "obrigado", "obrigada"}:
        return {
            "route": "direct",
            "reason": "saudação ou interação simples",
            "confidence": 0.95,
        }
    return {
        "route": "rag",
        "reason": "pergunta potencialmente clínica; seguir para busca documental",
        "confidence": 0.75,
    }


async def router_search_needed_node(state: ChatRAGState, *, settings: Settings) -> dict:
    """Decide se a próxima etapa é resposta direta ou fluxo RAG."""
    query = (state.get("query") or "").strip()
    steps = list(state.get("reasoning_steps") or [])
    trace: list[AuxLlmTraceEntry] = list(state.get("aux_llm_trace") or [])
    t0 = time.perf_counter()

    try:
        llm = build_llm(settings)
        router_messages = [
            SystemMessage(content=_ROUTER_SYSTEM),
            HumanMessage(content=query or ""),
        ]
        result = await tracked_ainvoke(
            llm,
            router_messages,
            call_type="router",
            trace=trace,
            settings=settings,
        )
        raw = (getattr(result, "content", None) or "").strip()
        if isinstance(raw, list):
            raw = "".join(str(part) for part in raw)
        data = _heuristic_router(query)
        if "rag" in raw.lower():
            data = {"route": "rag", "reason": "classificação do modelo", "confidence": 0.8}
        elif "direct" in raw.lower():
            data = {"route": "direct", "reason": "classificação do modelo", "confidence": 0.8}
    except Exception as exc:
        data = _heuristic_router(query)
        data["reason"] = f"{data['reason']} (fallback: {str(exc)[:120]})"

    search_needed = data["route"] == "rag"
    decision = {
        "route": data["route"],
        "search_needed": search_needed,
        "reason": data["reason"],
        "confidence": float(data.get("confidence") or 0.0),
    }
    steps.append(
        "Router: "
        + (
            "fluxo RAG selecionado."
            if search_needed
            else "resposta direta selecionada, sem busca documental."
        )
    )

    audit(
        "rag_search_router_done",
        kind="rag",
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        patient_id=state.get("patient_id") or None,
        query_snippet=truncate(query),
        router_result=decision,
    )

    return {
        "search_needed": search_needed,
        "generation_mode": "direct_answer" if not search_needed else state.get("generation_mode"),
        "router_decision": decision,
        "reasoning_steps": steps,
        "aux_llm_trace": trace,
    }


def route_search_needed(state: ChatRAGState) -> str:
    """Aresta do grafo entre resposta direta e fluxo RAG."""
    return "rag" if state.get("search_needed") else "direct"
