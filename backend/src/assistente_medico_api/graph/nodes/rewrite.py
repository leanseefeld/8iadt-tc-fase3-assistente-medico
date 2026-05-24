"""Nó de reescrita da pergunta para recuperação (RAG conversacional)."""

from __future__ import annotations

import time

from langchain_core.messages import HumanMessage, SystemMessage

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes.generate import _build_llm
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate
from assistente_medico_api.observability.clinical_audit_jsonl import ClinicalAuditAction, clinical_audit

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
    pid = state.get("patient_id") or None
    t0 = time.perf_counter()

    query = (state.get("query") or "").strip()
    steps = list(state.get("reasoning_steps") or [])
    if not query:
        steps.append("Reescrita: pergunta vazia — sem consulta de busca.")
        lm = round((time.perf_counter() - t0) * 1000, 2)
        audit(
            "rag_rewrite_done",
            kind="rag",
            latency_ms=lm,
            patient_id=pid,
            query_snippet="",
            retrieval_query_snippet="",
            used_history=False,
            note="empty_query",
        )
        clinical_audit(
            ClinicalAuditAction.REESCRITA_CONSULTA_RAG,
            patient_id=pid,
            descricao="Reescrita RAG: pergunta vazia.",
            detalhes={"latency_ms": lm, "used_history": False, "nota": "empty_query"},
            settings=settings,
        )
        return {"retrieval_query": "", "reasoning_steps": steps}

    hist = state.get("chat_history") or []
    if not hist:
        steps.append("Busca: sem histórico — usada pergunta literal na recuperação.")
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        audit(
            "rag_rewrite_done",
            kind="rag",
            latency_ms=latency_ms,
            patient_id=pid,
            query_snippet=truncate(query),
            retrieval_query_snippet=truncate(query),
            used_history=False,
        )
        clinical_audit(
            ClinicalAuditAction.REESCRITA_CONSULTA_RAG,
            patient_id=pid,
            descricao="Reescrita RAG: uso da pergunta literal (sem histórico no turno).",
            detalhes={
                "latency_ms": latency_ms,
                "used_history": False,
                "consulta_truncada": truncate(query, n=400),
            },
            settings=settings,
        )
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
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        audit(
            "rag_rewrite_done",
            kind="rag",
            latency_ms=latency_ms,
            patient_id=pid,
            query_snippet=truncate(query),
            retrieval_query_snippet=truncate(raw),
            used_history=True,
        )
        clinical_audit(
            ClinicalAuditAction.REESCRITA_CONSULTA_RAG,
            patient_id=pid,
            descricao="Reescrita RAG: consulta condensada a partir do histórico.",
            detalhes={
                "latency_ms": latency_ms,
                "used_history": True,
                "consulta_truncada": truncate(query, n=400),
                "consulta_recuperacao_truncada": truncate(raw, n=400),
            },
            settings=settings,
        )
        return {"retrieval_query": raw, "reasoning_steps": steps}
    except Exception:
        steps.append(
            "Busca: falha na reescrita — usada pergunta literal na recuperação."
        )
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        audit(
            "rag_rewrite_done",
            kind="rag",
            latency_ms=latency_ms,
            patient_id=pid,
            query_snippet=truncate(query),
            retrieval_query_snippet=truncate(query),
            used_history=True,
            note="rewrite_failed_fallback_literal",
        )
        clinical_audit(
            ClinicalAuditAction.REESCRITA_CONSULTA_RAG,
            patient_id=pid,
            descricao="Reescrita RAG falhou — fallback para pergunta literal.",
            detalhes={
                "latency_ms": latency_ms,
                "used_history": True,
                "nota": "rewrite_failed_fallback_literal",
                "consulta_truncada": truncate(query, n=400),
            },
            settings=settings,
        )
        return {"retrieval_query": query, "reasoning_steps": steps}
