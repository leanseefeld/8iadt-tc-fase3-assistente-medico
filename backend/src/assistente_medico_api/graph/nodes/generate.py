"""Nó de geração: prompt + ChatOllama."""

from __future__ import annotations

import httpx
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes.retrieve import format_context_block
from assistente_medico_api.graph.state import ChatRAGState

# Persona e limites de segurança para o assistente (pt-BR).
_SYSTEM_PROMPT = """\
Você é um assistente clínico de apoio a médicos no Brasil.
Use o contexto dos Protocolos Clínicos e Diretrizes Terapêuticas (PCDT) fornecido abaixo quando for relevante.
Cite as fontes pelo identificador [n] correspondente ao trecho.
Recomende mas não prescreva medicamentos, doses ou esquemas terapêuticos específicos: o médico responsável decide.
Se o contexto não for suficiente, diga claramente e evite inventar dados clínicos.
Responda em português do Brasil, de forma objetiva e profissional.\
"""


def _build_messages(state: ChatRAGState) -> list:
    """Monta as mensagens para o LLM a partir do estado atual do grafo."""
    docs = state.get("retrieved_docs") or []
    context = format_context_block(docs) if docs else "(Nenhum trecho recuperado.)"
    user_text = state.get("query") or ""
    human = (
        f"Pergunta do médico:\n{user_text}\n\n"
        f"Contexto (trechos PCDT):\n{context}\n\n"
        "Responda com base no contexto quando aplicável."
    )
    return [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human)]


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

    return {"answer": "".join(chunks)}
