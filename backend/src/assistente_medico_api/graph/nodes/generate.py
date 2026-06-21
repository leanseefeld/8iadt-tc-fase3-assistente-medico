"""Nó de geração: prompt + chat (endpoint OpenAI-compatível)."""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.llm_client import build_llm, serialize_messages
from assistente_medico_api.graph.context_formatting import format_context_block, format_context_preview
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.graph.clinical_query_understanding import normalize_text_for_match
from assistente_medico_api.observability.audit import audit, truncate
from assistente_medico_api.observability.clinical_audit_jsonl import ClinicalAuditAction, clinical_audit

# Persona e limites de segurança para o assistente (pt-BR).
GENERATE_SYSTEM_PROMPT = """\
Você é um assistente clínico de apoio a médicos no Brasil.
Responda sempre em português do Brasil, de forma objetiva e profissional.
Seja direto: vá ao ponto sem introduções desnecessárias, e use listas apenas quando genuinamente útil.
Nunca invente dados clínicos; quando recorrer ao conhecimento geral sem respaldo de protocolo, sinalize isso claramente.
Nunca utilize placeholders numéricos, textuais genéricos como "[Nome do Médico]" ou inicie com saudações. Vá direto ao resumo ou à resposta.
Só cumprimente se o médico cumprimentar primeiro.

## Contexto por turno
A cada turno você pode receber contexto estruturado pelo sistema: dados clínicos do paciente e/ou resultados de busca em PCDTs (Protocolos Clínicos e Diretrizes Terapêuticas).
O médico não vê esse contexto diretamente — ele só vê suas próprias mensagens e suas respostas.
Use o contexto clínico para personalizar a resposta quando aplicável; não extrapole além do que foi fornecido.
Use pronomes adequados ao gênero do paciente.

## Resultados de busca em PCDTs
Quando resultados forem fornecidos:
- Utilize apenas os trechos relevantes para a pergunta; cite cada um pelo identificador [n].
- Ignore trechos que não contribuam para a resposta.
- Se nenhum resultado for pertinente, informe brevemente que documentos relevantes não foram encontrados — sem listar ou descrever os documentos irrelevantes.

Quando não houver resultados (pergunta conversacional ou de acompanhamento):
- Responda com base no histórico da conversa e no seu conhecimento geral.

## Foco da resposta
Responda diretamente à "Mensagem do médico:", usando o restante do contexto apenas como subsídio.

## Formatação de exames e ações clínicas
Quando apresentar exames pendentes do paciente, use lista markdown:
**Exames pendentes:**
- **[nome do exame]** — solicitado [tempo relativo]

Quando listar ações clínicas sugeridas ou recomendações de protocolo, use lista numerada com tipo entre colchetes:
**Ações sugeridas:**
1. [Exame] descrição
2. [Prescrição] descrição
3. [Observação] descrição
4. [Reavaliação] descrição

Tipos válidos: [Exame], [Prescrição], [Observação], [Reavaliação].\
"""


# Compatibilidade com testes que fazem monkeypatch em generate._build_llm.
_build_llm = build_llm


def _build_messages(state: ChatRAGState) -> list:
    """Monta as mensagens para o LLM a partir do estado atual do grafo."""
    docs = state.get("retrieved_docs") or []
    context = format_context_block(docs) if docs else "(Nenhum trecho recuperado.)"
    user_text = state.get("query") or ""
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
    out: list = [SystemMessage(content=GENERATE_SYSTEM_PROMPT)]
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


def _structured_disease_name(state: ChatRAGState) -> str:
    expansion = state.get("query_expansion") or {}
    structured = state.get("structured_terms") or expansion.get("structured_terms") or {}
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
    structured = state.get("structured_terms") or expansion.get("structured_terms") or {}
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
    if not docs or not any(_doc_matches_detected_disease(doc, disease_norm) for doc in docs):
        return f"Não encontrei trechos PCDT compatíveis com {disease_name} para responder com segurança."
    return None


def _prompt_context_preview(state: ChatRAGState, max_chars: int = 1200) -> str:
    docs = state.get("retrieved_docs") or []
    return format_context_preview(docs, max_docs=2, max_chars=max_chars)


async def _stream_answer(
    state: ChatRAGState,
    settings: Settings,
) -> tuple[str, list[BaseMessage]]:
    """Gera resposta via streaming; retorna texto e mensagens enviadas ao LLM."""
    llm = _build_llm(settings)
    messages = _build_messages(state)
    chunks: list[str] = []
    async for chunk in llm.astream(messages):
        if isinstance(chunk, BaseMessage):
            piece = chunk.content
        else:
            piece = getattr(chunk, "content", None) or str(chunk)
        if isinstance(piece, list):
            piece = "".join(str(p) for p in piece)
        if piece:
            chunks.append(str(piece))
    return "".join(chunks), messages


async def _generate_grounded_answer(state: ChatRAGState, settings: Settings) -> dict:
    """Gera resposta grounded usando apenas o contexto validado."""
    pid = state.get("patient_id") or None
    t0 = time.perf_counter()
    docs = state.get("retrieved_docs") or []
    expansion = state.get("query_expansion") or {}
    structured = state.get("structured_terms") or expansion.get("structured_terms") or {}
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
        clinical_audit(
            ClinicalAuditAction.GERACAO_RESPOSTA_RAG,
            patient_id=pid,
            descricao="Resposta do assistente: caminho controlado (contexto PCDT incompatível com doença detectada).",
            detalhes={
                "latency_ms": latency_ms,
                "tipo": "resposta_controlada",
                "motivo": "detected_disease_without_compatible_context",
                "caracteres_resposta": len(controlled_answer),
                "documentos_recuperados": len(docs),
            },
            settings=settings,
        )
        return {
            "answer": controlled_answer,
            "rag_audit_payload": audit_payload,
            "generate_llm_output": controlled_answer,
        }

    answer, messages = await _stream_answer(state, settings)
    serialized_input = serialize_messages(messages)
    stems = sorted({d.metadata.get("source_stem", "?") for d in docs}) if docs else []
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    audit(
        "rag_generate_done",
        kind="rag",
        latency_ms=latency_ms,
        patient_id=pid,
        query_snippet=truncate(state.get("query") or ""),
        answer_chars=len(answer),
        retrieved_count=len(docs),
        source_stems=stems,
        controlled_response=False,
    )
    clinical_audit(
        ClinicalAuditAction.GERACAO_RESPOSTA_RAG,
        patient_id=pid,
        descricao="Geração da resposta do assistente (LLM) concluída.",
        detalhes={
            "latency_ms": latency_ms,
            "tipo": "geracao_llm",
            "caracteres_resposta": len(answer),
            "documentos_recuperados": len(docs),
            "stems_fonte_resumo": stems[:15],
        },
        settings=settings,
    )
    # Histórico atualizado no guardrail_node, que conhece a resposta final
    # (pode ter sido substituída ou modificada pelo guardrail).
    return {
        "answer": answer,
        "rag_audit_payload": audit_payload,
        "generate_llm_input": serialized_input,
        "generate_llm_output": answer,
    }


async def _generate_direct_answer(state: ChatRAGState, settings: Settings) -> dict:
    """Gera resposta direta sem busca documental."""
    pid = state.get("patient_id") or None
    t0 = time.perf_counter()
    query = normalize_text_for_match(state.get("query") or "")
    audit(
        "rag_generate_context_received",
        kind="rag",
        patient_id=pid,
        retrieved_docs_count=0,
        disease=None,
        expanded_query=None,
        top_source_stems=[],
        top_sections=[],
        prompt_context_preview="",
    )
    answer, messages = await _stream_answer(state, settings)
    serialized_input = serialize_messages(messages)
    audit(
        "rag_generate_direct_answer",
        kind="rag",
        patient_id=pid,
        router_decision=state.get("router_decision") or {},
    )
    audit(
        "rag_generate_done",
        kind="rag",
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        patient_id=pid,
        query_snippet=truncate(state.get("query") or ""),
        answer_chars=len(answer),
        retrieved_count=0,
        source_stems=[],
        controlled_response=False,
    )
    return {
        "answer": answer,
        "generation_mode": "direct_answer",
        "generate_llm_input": serialized_input,
        "generate_llm_output": answer,
    }


async def _generate_insufficient_context(state: ChatRAGState, settings: Settings) -> dict:
    """Gera resposta de insuficiência de contexto com streaming."""
    pid = state.get("patient_id") or None
    t0 = time.perf_counter()
    answer, messages = await _stream_answer(state, settings)
    serialized_input = serialize_messages(messages)
    structured = state.get("structured_terms") or {}
    rerank_result = state.get("rerank_result") or {}
    disease = structured.get("diretriz") or structured.get("disease") or "a condição solicitada"
    reason = rerank_result.get("insufficiency_reason") or state.get(
        "insufficiency_reason") or "contexto recuperado insuficiente"
    audit(
        "rag_generate_insufficient_context",
        kind="rag",
        patient_id=pid,
        disease=disease,
        insufficiency_reason=reason,
    )
    audit(
        "rag_generate_done",
        kind="rag",
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        patient_id=pid,
        query_snippet=truncate(state.get("query") or ""),
        answer_chars=len(answer),
        retrieved_count=len(state.get("retrieved_docs") or []),
        source_stems=[],
        controlled_response=False,
    )
    return {
        "answer": answer,
        "generation_mode": "insufficient_context",
        "generate_llm_input": serialized_input,
        "generate_llm_output": answer,
    }


async def generate_node(state: ChatRAGState, settings: Settings) -> dict:
    """Nó público único de geração: escolhe a estratégia pelo `generation_mode`."""
    mode = str(state.get("generation_mode") or "grounded_answer")
    if mode == "direct_answer":
        return await _generate_direct_answer(state, settings)
    if mode == "insufficient_context":
        return await _generate_insufficient_context(state, settings)
    return await _generate_grounded_answer(state, settings)
