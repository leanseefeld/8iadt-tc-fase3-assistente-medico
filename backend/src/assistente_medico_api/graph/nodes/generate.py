"""Nó de geração: prompt + ChatOllama."""

from __future__ import annotations

import time

import httpx
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_ollama import ChatOllama

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes.retrieve import format_context_block
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate

# Persona e limites de segurança para o assistente (pt-BR).
_SYSTEM_PROMPT = """\
Você é um assistente clínico de apoio a médicos no Brasil.
Você realizou uma busca por Protocolos Clínicos e Diretrizes Terapêuticas (PCDT) para responder a mensagem.
Cite os resultados pelo identificador [n] correspondente ao trecho.
Use exclusivamente os documentos recuperados abaixo. Quando responder, mencione a diretriz, a seção e as páginas quando disponíveis.
Se os documentos não contiverem informação suficiente, diga isso claramente.
Recomende mas não prescreva medicamentos, doses ou esquemas terapêuticos específicos: o médico responsável decide.
Se os resultados da busca não forem suficientes, diga que documentos relevantes não foram encontrados.
Evite inventar dados clínicos.
Evite descrever ou mencionar resultados da busca que não sejam construtivos para a pergunta do médico.
Responda em português do Brasil, de forma objetiva e profissional, apenas com informações relevantes à interação.\
"""


def _build_messages(state: ChatRAGState) -> list:
    """Monta as mensagens para o LLM a partir do estado atual do grafo."""
    docs = state.get("retrieved_docs") or []
    context = format_context_block(docs) if docs else "(Nenhum trecho recuperado.)"
    user_text = state.get("query") or ""
    query_expansion = state.get("query_expansion") or {}
    understanding = _format_clinical_understanding(
        state.get("clinical_understanding") or {},
        query_expansion.get("structured_terms") or {},
    )
    # Bloco PCDT só na pergunta corrente (turno final do utilizador).
    final_human = (
        f"Pergunta do médico:\n{user_text}\n\n"
        f"Entendimento da pergunta:\n{understanding}\n\n"
        f"Contexto (trechos PCDT):\n{context}\n\n"
        "Instruções:\n"
        "- Responda com base exclusivamente nos documentos recuperados.\n"
        "- Use o entendimento da pergunta apenas como apoio para priorizar os documentos; não trate esse entendimento como fonte clínica.\n"
        "- Priorize documentos cuja diretriz, doença, seção e páginas sejam compatíveis com a pergunta do médico.\n"
        "- Se a pergunta pedir uma seção específica, como critérios de inclusão, critérios de exclusão, diagnóstico, tratamento, monitoramento ou medicamentos, priorize documentos dessa seção.\n"
        "- Se os documentos recuperados não contiverem a informação solicitada, diga claramente que os documentos recuperados são insuficientes.\n"
        "- Cite a diretriz, a seção e as páginas quando disponíveis.\n"
        "- Não invente condutas, doses, critérios, contraindicações ou recomendações ausentes nos documentos.\n"
        "- Não use conhecimento externo aos documentos recuperados.\n"
    )
    out: list = [SystemMessage(content=_SYSTEM_PROMPT)]
    for turn in state.get("chat_history") or []:
        text = (turn.get("content") or "").strip()
        if not text:
            continue
        role = turn.get("role")
        if role == "user":
            out.append(HumanMessage(content=text))
        elif role == "assistant":
            out.append(AIMessage(content=text))
    out.append(HumanMessage(content=final_human))
    return out


def _format_clinical_understanding(understanding: dict, structured_terms: dict | None = None) -> str:
    structured_terms = structured_terms or {}
    disease = understanding.get("detected_disease") or {}
    entities = understanding.get("linked_entities") or []
    candidates = understanding.get("catalog_candidates") or []
    structured_disease = structured_terms.get("diretriz") or structured_terms.get("disease")
    structured_cids = structured_terms.get("cid10_codes") or []
    structured_sections = structured_terms.get("preferred_sections") or []
    return "\n".join(
        [
            f"- Intenção: {structured_terms.get('intent') or (understanding.get('intent_result') or {}).get('intent') or understanding.get('intent') or 'não detectada'}",
            f"- Doença/Diretriz: {structured_disease or disease.get('name') or 'nenhuma'}",
            f"- CID-10: {', '.join(structured_cids) or ', '.join(understanding.get('detected_cid10_codes') or []) or 'nenhum'}",
            f"- Seções preferenciais: {_format_items(structured_sections)}",
            f"- Entidades biomédicas linkadas: {_format_items([e.get('canonical') or e.get('text') for e in entities])}",
            f"- Candidatos do catálogo: {_format_items([c.get('diretriz') or c.get('disease') for c in candidates])}",
        ]
    )


def _format_items(values: list, limit: int = 5) -> str:
    items = [str(value).strip() for value in values if str(value or "").strip()]
    if not items:
        return "nenhuma"
    suffix = "..." if len(items) > limit else ""
    return ", ".join(items[:limit]) + suffix


def _build_llm(settings: Settings) -> ChatOllama:
    # Timeout aplicado no cliente HTTP (httpx) — vale para qualquer nó que use este helper.
    # connect=10s evita espera longa se Ollama não responde; read é o tempo de geração.
    timeout = httpx.Timeout(settings.llm_stream_timeout_s, connect=10.0)
    return ChatOllama(
        model=settings.ollama_chat_model,
        base_url=settings.ollama_base_url,
        temperature=0.2,
        async_client_kwargs={"timeout": timeout},
        client_kwargs={"timeout": timeout},
    )


async def generate_node(state: ChatRAGState, settings: Settings) -> dict:
    """
    Nó assíncrono do grafo: acumula tokens via astream para que
    graph.astream_events() emita eventos on_chat_model_stream por token.
    """
    pid = state.get("patient_id") or None
    t0 = time.perf_counter()
    docs = state.get("retrieved_docs") or []

    llm = _build_llm(settings)
    messages = _build_messages(state)

    # Acumula tokens; os eventos on_chat_model_stream são emitidos
    # automaticamente pelo sistema de callbacks do LangChain/LangGraph.
    # O timeout é gerenciado pelo cliente httpx em _build_llm; exceções de rede
    # (ReadTimeout, ConnectTimeout) propagam normalmente para o chamador.
    chunks: list[str] = []
    async for chunk in llm.astream(messages):
        piece = chunk.content if isinstance(chunk, BaseMessage) else str(chunk)
        if isinstance(piece, list):
            piece = "".join(str(p) for p in piece)
        if piece:
            chunks.append(str(piece))

    ans = "".join(chunks)
    stems = sorted({d.metadata.get("source_stem", "?") for d in docs}) if docs else []
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    audit(
        "rag_generate_done",
        kind="rag",
        latency_ms=latency_ms,
        patient_id=pid,
        query_snippet=truncate(state.get("query") or ""),
        answer_chars=len(ans),
        retrieved_count=len(docs),
        source_stems=stems,
    )
    # Histórico atualizado no guardrail_node, que conhece a resposta final
    # (pode ter sido substituída ou modificada pelo guardrail).
    return {"answer": ans}
