"""Nó de reescrita da pergunta para recuperação (RAG conversacional)."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes.generate import _build_llm
from assistente_medico_api.graph.state import ChatRAGState

_REWRITE_SYSTEM = """\
Você reformula a última pergunta do médico como uma única consulta autocontida para busca \
por similaridade em documentos dos Protocolos Clínicos e Diretrizes Terapêuticas (PCDT) do Brasil.
Preserve termos clínicos e CID/procedimentos quando citados no histórico.
Responda apenas com a consulta reformulada, sem prefixos nem explicações.\
"""


def _history_transcript(state: ChatRAGState) -> str:
    lines: list[str] = []
    for turn in state.get("chat_history") or []:
        text = (turn.get("content") or "").strip()
        if not text:
            continue
        role = turn.get("role")
        if role == "user":
            lines.append(f"Médico: {text}")
        elif role == "assistant":
            lines.append(f"Assistente: {text}")
    return "\n".join(lines)


async def rewrite_query_node(state: ChatRAGState, settings: Settings) -> dict:
    """
    Define retrieval_query: cópia da pergunta atual se não há histórico; caso contrário, LLM
    condensa pergunta + histórico numa string de busca.
    """
    query = (state.get("query") or "").strip()
    steps = list(state.get("reasoning_steps") or [])
    if not query:
        steps.append("Reescrita: pergunta vazia — sem consulta de busca.")
        return {"retrieval_query": "", "reasoning_steps": steps}

    hist = state.get("chat_history") or []
    if not hist:
        steps.append("Busca: sem histórico — usada pergunta literal na recuperação.")
        return {"retrieval_query": query, "reasoning_steps": steps}

    transcript = _history_transcript(state)
    llm = _build_llm(settings)
    human = (
        f"Histórico da conversa:\n{transcript}\n\n"
        f"Última pergunta do médico:\n{query}\n\n"
        "Reformule em uma consulta única para busca nos PCDTs."
    )
    try:
        result = await llm.ainvoke(
            [SystemMessage(content=_REWRITE_SYSTEM), HumanMessage(content=human)]
        )
        raw = (getattr(result, "content", None) or "").strip()
        if isinstance(raw, list):
            raw = "".join(str(p) for p in raw)
        if not raw:
            raise ValueError("resposta vazia do modelo")
        steps.append("Busca: pergunta reescrita com o histórico para recuperação.")
        return {"retrieval_query": raw, "reasoning_steps": steps}
    except Exception:
        steps.append(
            "Busca: falha na reescrita — usada pergunta literal na recuperação."
        )
        return {"retrieval_query": query, "reasoning_steps": steps}
