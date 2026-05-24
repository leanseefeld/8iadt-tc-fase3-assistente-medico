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
from assistente_medico_api.graph.context_formatting import format_context_block, format_context_preview
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.graph.clinical_query_understanding import normalize_text_for_match
from assistente_medico_api.observability.audit import audit, truncate
from assistente_medico_api.services.rag_pipeline_service import (
    CONTEXT_SUFFICIENT,
    append_audit_step,
    build_pipeline_audit,
)

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
    rewrite_result = state.get("rewrite_result") or {}
    query_expansion = state.get("query_expansion") or {}
    structured_terms = state.get("structured_terms") or rewrite_result.get("structured_terms") or query_expansion.get("structured_terms") or {}
    understanding = _format_clinical_understanding(
        state.get("clinical_understanding") or rewrite_result.get("clinical_understanding") or {},
        structured_terms,
        (state.get("rerank_result") or {}).get("debug") or {},
    )
    # Bloco PCDT só na pergunta corrente (turno final do utilizador).
    final_human = (
        f"Pergunta do médico:\n{user_text}\n\n"
        f"Entendimento da pergunta:\n{understanding}\n\n"
        f"Contexto (trechos PCDT):\n{context}\n\n"
        "Instruções de resposta:\n"
        "- Use apenas o contexto PCDT acima.\n"
        "- Não expanda ou redefina siglas se a Doença/Diretriz já foi detectada no entendimento estruturado.\n"
        "- Se o contexto não responder à pergunta sobre a Doença/Diretriz detectada, diga que os documentos recuperados não foram suficientes.\n"
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
    structured = (
        state.get("structured_terms")
        or (state.get("rewrite_result") or {}).get("structured_terms")
        or (state.get("query_expansion") or {}).get("structured_terms")
        or {}
    )
    understanding = state.get("clinical_understanding") or {}
    disease = understanding.get("detected_disease") or {}
    return str(
        structured.get("diretriz")
        or structured.get("disease")
        or disease.get("name")
        or ""
    ).strip()


def _structured_disease_norm(state: ChatRAGState) -> str:
    structured = (
        state.get("structured_terms")
        or (state.get("rewrite_result") or {}).get("structured_terms")
        or (state.get("query_expansion") or {}).get("structured_terms")
        or {}
    )
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
    return format_context_preview(docs, max_chars=max_chars)


async def generate_node(state: ChatRAGState, settings: Settings) -> dict:
    """
    Nó assíncrono do grafo: acumula tokens via astream para que
    graph.astream_events() emita eventos on_chat_model_stream por token.
    """
    audit("generate: start", kind="rag")
    pid = state.get("patient_id") or None
    t0 = time.perf_counter()
    docs = state.get("retrieved_docs") or []
    rewrite_result = state.get("rewrite_result") or {}
    query_expansion = state.get("query_expansion") or {}
    structured = state.get("structured_terms") or rewrite_result.get("structured_terms") or query_expansion.get("structured_terms") or {}
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
        expanded_query=state.get("expanded_query") or rewrite_result.get("expanded_query"),
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
        out = {
            "answer": controlled_answer,
        }
        generation_result = {"mode": "grounded", "answer": controlled_answer}
        audit_trace = append_audit_step(
            {**dict(state), **out, "generation_result": generation_result},
            node="generate_grounded_answer",
            output_summary={"mode": "grounded", "controlled": True},
            settings=settings,
        )
        return {
            **out,
            "generation_result": generation_result,
            "audit_trace": audit_trace,
            "rag_audit_payload": build_pipeline_audit({**dict(state), **out, "generation_result": generation_result, "audit_trace": audit_trace}, generate_mode="grounded"),
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
    out = {"answer": ans}
    generation_result = {"mode": "grounded", "answer": ans}
    audit_trace = append_audit_step(
        {**dict(state), **out, "generation_result": generation_result},
        node="generate_grounded_answer",
        output_summary={"mode": "grounded", "answer_chars": len(ans), "sources": len(stems)},
        settings=settings,
    )
    return {
        **out,
        "generation_result": generation_result,
        "audit_trace": audit_trace,
        "rag_audit_payload": build_pipeline_audit({**dict(state), **out, "generation_result": generation_result, "audit_trace": audit_trace}, generate_mode="grounded"),
    }


async def generate_grounded_answer_node(state: ChatRAGState, settings: Settings) -> dict:
    """Generate grounded answer using validated retrieved_docs."""
    quality = (state.get("rerank_result") or {}).get("context_quality")
    if getattr(settings, "rag_require_source_for_clinical_answer", True) and quality != CONTEXT_SUFFICIENT:
        return await generate_insufficient_context_node(
            {
                **dict(state),
                "insufficiency_reason": state.get("insufficiency_reason") or "contexto não validado como suficiente",
            },
            settings,
        )
    return await generate_node(state, settings)


async def generate_insufficient_context_node(state: ChatRAGState, settings: Settings) -> dict:
    """Return controlled insufficiency answer without asking the LLM for clinical content."""
    structured = (
        state.get("structured_terms")
        or (state.get("rewrite_result") or {}).get("structured_terms")
        or (state.get("query_expansion") or {}).get("structured_terms")
        or {}
    )
    rerank_result = state.get("rerank_result") or {}
    disease = structured.get("diretriz") or structured.get("disease") or "a condição solicitada"
    intent = structured.get("intent") or "a pergunta"
    reason = rerank_result.get("insufficiency_reason") or state.get("insufficiency_reason") or "contexto recuperado insuficiente"
    found_sections = rerank_result.get("found_sections") or []
    answer = (
        f"Não encontrei trechos suficientes nos PCDTs recuperados para responder com segurança. "
        f"Identifiquei a pergunta como relacionada a {disease} e {intent}, "
        f"mas os trechos recuperados não foram suficientes para responder com segurança. "
        f"Motivo: {reason}."
    )
    if found_sections:
        answer += f" Seções encontradas: {', '.join(str(v) for v in found_sections[:5] if v)}."
    out = {"answer": answer}
    audit(
        "rag_generate_insufficient_context",
        kind="rag",
        patient_id=state.get("patient_id") or None,
        disease=disease,
        insufficiency_reason=reason,
    )
    generation_result = {"mode": "insufficient", "answer": answer}
    audit_trace = append_audit_step(
        {**dict(state), **out, "generation_result": generation_result},
        node="generate_insufficient_context",
        output_summary={"mode": "insufficient", "reason": reason},
        settings=settings,
    )
    return {
        **out,
        "generation_result": generation_result,
        "audit_trace": audit_trace,
        "rag_audit_payload": build_pipeline_audit({**dict(state), **out, "generation_result": generation_result, "audit_trace": audit_trace}, generate_mode="insufficient"),
    }


async def generate_direct_answer_node(state: ChatRAGState, settings: Settings) -> dict:
    """Answer non-RAG interactions without inventing clinical guidance."""
    query = normalize_text_for_match(state.get("query") or "")
    if any(term in query for term in ("ola", "oi", "bom dia", "boa tarde", "boa noite")):
        answer = "Olá. Como posso ajudar com uma pergunta clínica ou consulta a PCDTs?"
    else:
        answer = (
            "Posso ajudar a consultar PCDTs e organizar informações clínicas. "
            "Para orientação clínica específica, reformule a pergunta mencionando a condição, CID, protocolo ou conduta desejada."
        )
    out = {"answer": answer}
    audit(
        "rag_generate_direct_answer",
        kind="rag",
        patient_id=state.get("patient_id") or None,
        router_decision=state.get("router_decision") or {},
    )
    generation_result = {"mode": "direct", "answer": answer}
    audit_trace = append_audit_step(
        {**dict(state), **out, "generation_result": generation_result},
        node="generate_direct_answer",
        output_summary={"mode": "direct"},
        settings=settings,
    )
    return {
        **out,
        "generation_result": generation_result,
        "audit_trace": audit_trace,
        "rag_audit_payload": build_pipeline_audit({**dict(state), **out, "generation_result": generation_result, "audit_trace": audit_trace}, generate_mode="direct"),
    }
