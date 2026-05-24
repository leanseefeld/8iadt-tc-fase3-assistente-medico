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
from assistente_medico_api.graph.rag_enhancement import format_context_document
from assistente_medico_api.graph.nodes.retrieve import format_context_block
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.graph.clinical_query_understanding import normalize_text_for_match
from assistente_medico_api.observability.audit import audit, truncate

# Persona e limites de segurança para o assistente (pt-BR).
_SYSTEM_PROMPT = """\
Você gera respostas para um assistente clínico de apoio a médicos no Brasil.
Responda em português do Brasil, de forma objetiva, profissional e fluída para manter o tom da conversa.

Uma busca por Protocolos Clínicos e Diretrizes Terapêuticas (PCDT) pode ter sido realizada para responder a pergunta.

Quando resultados de busca nos PCDTs forem fornecidos:
- Use-os quando forem relevantes para a pergunta; cite pelo identificador [n] correspondente.
- Ignore trechos que não sejam construtivos para a pergunta.
- Se nenhum resultado for suficiente, diga que documentos relevantes não foram encontrados.
- Mencione apenas os trechos que sejam relevantes para a pergunta, evitando descrever trechos irrelevantes.

Quando não houver resultados de busca (pergunta conversacional ou de acompanhamento):
- Responda com base no histórico da conversa e no seu conhecimento geral.
- Evite inventar dados clínicos; se necessário, sinalize que é conhecimento geral sem respaldo de protocolo.

Você recebe contexto relevante em cada turno da conversa, mas deve responder diretamente ao conteúdo de "Mensagem do médico:".
O médico não tem acesso direto ao contexto, apenas as mensagens que ele mesmo enviou e o que você respondeu.
Assuma que quem estruturou o contexto foi você mesmo, não o médico.

Use o contexto clínico do paciente para personalizar a resposta quando aplicável. Não invente dados além do fornecido.
Use pronomes adequados para o gênero do paciente.
Só cumprimente se for cumprimentado.\
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
        query_expansion.get("_complementary_retrieve_info") or {},
    )
    patient_context = (state.get("patient_context") or "").strip()
    patient_block = (
        f"Contexto clínico do paciente:\n{patient_context}\n\n"
        if patient_context
        else ""
    )
    # Bloco PCDT só na pergunta corrente (turno final do utilizador).
    final_human = (
        f"{patient_block}\n\n"
        f"Resultado da busca por trechos PCDT:\n{context}\n\n"
        f"Mensagem do médico:\n{user_text}\n\n"

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


def _format_clinical_understanding(
    understanding: dict,
    structured_terms: dict | None = None,
    complementary_info: dict | None = None,
) -> str:
    structured_terms = structured_terms or {}
    complementary_info = complementary_info or {}
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
            f"- Seção preferida encontrada: {'não' if complementary_info.get('preferred_section_not_found') else 'sim' if complementary_info.get('preferred_section_found') else 'não informado'}",
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


def _structured_disease_name(state: ChatRAGState) -> str:
    expansion = state.get("query_expansion") or {}
    structured = expansion.get("structured_terms") or {}
    understanding = state.get("clinical_understanding") or {}
    disease = understanding.get("detected_disease") or {}
    return str(
        structured.get("diretriz")
        or structured.get("disease")
        or disease.get("name")
        or ""
    ).strip()


def _structured_disease_norm(state: ChatRAGState) -> str:
    expansion = state.get("query_expansion") or {}
    structured = expansion.get("structured_terms") or {}
    understanding = state.get("clinical_understanding") or {}
    disease = understanding.get("detected_disease") or {}
    return normalize_text_for_match(
        structured.get("disease_normalized")
        or structured.get("diretriz")
        or structured.get("disease")
        or disease.get("normalized")
        or disease.get("name")
        or ""
    )


def _doc_matches_detected_disease(doc, disease_norm: str) -> bool:
    if not disease_norm:
        return True
    meta = dict(getattr(doc, "metadata", {}) or {})
    for key in ("disease_normalized", "disease", "diretriz_normalized", "diretriz"):
        if normalize_text_for_match(meta.get(key)) == disease_norm:
            return True
    return False


def _context_mismatch_answer(state: ChatRAGState) -> str | None:
    disease_norm = _structured_disease_norm(state)
    disease_name = _structured_disease_name(state)
    if not disease_norm or not disease_name:
        return None

    docs = state.get("retrieved_docs") or []
    if not docs:
        return (
            f"Não encontrei trechos PCDT compatíveis com {disease_name} "
            "para responder com segurança."
        )
    if not any(_doc_matches_detected_disease(doc, disease_norm) for doc in docs):
        return (
            f"Não encontrei trechos PCDT compatíveis com {disease_name} "
            "para responder com segurança."
        )
    return None


def _prompt_context_preview(state: ChatRAGState, max_chars: int = 1200) -> str:
    docs = state.get("retrieved_docs") or []
    preview = "\n\n---\n\n".join(
        format_context_document(doc, i)
        for i, doc in enumerate(docs[:2], start=1)
    )
    return preview[:max_chars]


async def generate_node(state: ChatRAGState, settings: Settings) -> dict:
    """
    Nó assíncrono do grafo: acumula tokens via astream para que
    graph.astream_events() emita eventos on_chat_model_stream por token.
    """
    pid = state.get("patient_id") or None
    t0 = time.perf_counter()
    docs = state.get("retrieved_docs") or []
    expansion = state.get("query_expansion") or {}
    structured = expansion.get("structured_terms") or {}
    top_stems = [d.metadata.get("source_stem") for d in docs[:5]]
    top_sections = [d.metadata.get("section") or d.metadata.get("header_1") for d in docs[:5]]
    context_preview = _prompt_context_preview(state)

    audit_payload = dict(state.get("rag_audit_payload") or {})
    if audit_payload is not None:
        audit_payload["prompt_context_preview"] = context_preview

    audit(
        "rag_generate_context_received",
        kind="rag",
        patient_id=pid,
        retrieved_docs_count=len(docs),
        disease=structured.get("diretriz") or structured.get("disease"),
        expanded_query=expansion.get("expanded_query"),
        top_source_stems=top_stems,
        top_sections=top_sections,
        prompt_context_preview=truncate(context_preview, n=1000),
    )

    controlled_answer = _context_mismatch_answer(state)
    if controlled_answer is not None:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        audit(
            "rag_generate_done",
            kind="rag",
            latency_ms=latency_ms,
            patient_id=pid,
            query_snippet=truncate(state.get("query") or ""),
            answer_chars=len(controlled_answer),
            retrieved_count=len(docs),
            source_stems=top_stems,
            controlled_response=True,
            reason="detected_disease_without_compatible_context",
        )
        return {
            "answer": controlled_answer,
            "rag_audit_payload": audit_payload,
        }

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
        controlled_response=False,
    )
    # Histórico atualizado no guardrail_node, que conhece a resposta final
    # (pode ter sido substituída ou modificada pelo guardrail).
    return {"answer": ans, "rag_audit_payload": audit_payload}
