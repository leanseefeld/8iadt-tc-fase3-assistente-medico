"""Nós finais de geração da resposta do chat médico."""

from __future__ import annotations

import time

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.context_formatting import format_context_block, format_context_preview
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.graph.clinical_query_understanding import normalize_text_for_match
from assistente_medico_api.observability.audit import audit, truncate

_SYSTEM_PROMPT = """\
Você é um assistente clínico de apoio a médicos no Brasil.
Responda em português do Brasil, de forma objetiva e profissional.
Use apenas o contexto disponível quando houver fonte documental.
Não invente dados clínicos.
Não prescreva doses, posologias ou esquemas terapêuticos específicos.\
"""

_DIRECT_SYSTEM_PROMPT = """\
Você é um assistente clínico de apoio a médicos no Brasil.
Responda de forma curta e útil a saudações ou perguntas genéricas.
Não invente dados clínicos e não sugira condutas sem contexto documental.\
"""

_INSUFFICIENT_SYSTEM_PROMPT = """\
Você é um assistente clínico de apoio a médicos no Brasil.
Explique que o contexto recuperado foi insuficiente para responder com segurança.
Oriente o médico a revisar o PCDT correspondente ou refinar a pergunta.
Responda em português do Brasil.\
"""


def _build_llm(settings: Settings) -> ChatOllama:
    """Cria o cliente Ollama usado pelos nós finais e pelo guardrail."""
    timeout = httpx.Timeout(settings.llm_stream_timeout_s, connect=10.0)
    return ChatOllama(
        model=settings.ollama_chat_model,
        base_url=settings.ollama_base_url,
        temperature=0.2,
        async_client_kwargs={"timeout": timeout},
        client_kwargs={"timeout": timeout},
    )


def _format_items(values: list, limit: int = 5) -> str:
    items = [str(value).strip() for value in values if str(value or "").strip()]
    if not items:
        return "nenhuma"
    suffix = "..." if len(items) > limit else ""
    return ", ".join(items[:limit]) + suffix


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


def _build_messages(state: ChatRAGState, *, mode: str = "grounded") -> list:
    """Monta as mensagens para o LLM a partir do estado atual do grafo."""
    docs = state.get("retrieved_docs") or []
    context = format_context_block(docs) if docs else "(Nenhum trecho recuperado.)"
    user_text = state.get("query") or ""
    query_expansion = state.get("query_expansion") or {}
    understanding = _format_clinical_understanding(
        state.get("clinical_understanding") or {},
        state.get("structured_terms") or query_expansion.get("structured_terms") or {},
        query_expansion.get("_complementary_retrieve_info") or {},
    )

    if mode == "direct":
        human = (
            f"Pergunta do médico:\n{user_text}\n\n"
            "Responda sem usar contexto documental. "
            "Se for saudação, responda de forma breve e profissional."
        )
        system = _DIRECT_SYSTEM_PROMPT
    elif mode == "insufficient":
        human = (
            f"Pergunta do médico:\n{user_text}\n\n"
            f"Motivo da insuficiência:\n{state.get('insufficiency_reason') or 'contexto recuperado insuficiente'}\n\n"
            f"Contexto recuperado:\n{context}\n\n"
            "Explique que a base recuperada foi insuficiente e oriente a refinar a pergunta."
        )
        system = _INSUFFICIENT_SYSTEM_PROMPT
    else:
        human = (
            f"Pergunta do médico:\n{user_text}\n\n"
            f"Entendimento da pergunta:\n{understanding}\n\n"
            f"Contexto (trechos PCDT):\n{context}\n\n"
            "Instruções de resposta:\n"
            "- Use apenas o contexto PCDT acima.\n"
            "- Não expanda ou redefina siglas se a Doença/Diretriz já foi detectada no entendimento estruturado.\n"
            "- Se o contexto não responder à pergunta sobre a Doença/Diretriz detectada, diga que os documentos recuperados não foram suficientes.\n"
        )
        system = _SYSTEM_PROMPT

    out: list = [SystemMessage(content=system)]
    for turn in state.get("chat_history") or []:
        text = (turn.get("content") or "").strip()
        if not text:
            continue
        role = turn.get("role")
        if role == "user":
            out.append(HumanMessage(content=text))
        elif role == "assistant":
            out.append(AIMessage(content=text))
    out.append(HumanMessage(content=human))
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


async def _stream_answer(state: ChatRAGState, settings: Settings, *, mode: str) -> str:
    llm = _build_llm(settings)
    messages = _build_messages(state, mode=mode)
    chunks: list[str] = []
    async for chunk in llm.astream(messages):
        piece = chunk.content if isinstance(chunk, BaseMessage) else str(chunk)
        if isinstance(piece, list):
            piece = "".join(str(p) for p in piece)
        if piece:
            chunks.append(str(piece))
    return "".join(chunks)


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
        audit(
            "rag_generate_done",
            kind="rag",
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            patient_id=pid,
            query_snippet=truncate(state.get("query") or ""),
            answer_chars=len(controlled_answer),
            retrieved_count=len(docs),
            source_stems=top_stems,
            controlled_response=True,
            reason="detected_disease_without_compatible_context",
        )
        return {"answer": controlled_answer, "generation_mode": "grounded_answer"}

    answer = await _stream_answer(state, settings, mode="grounded")
    stems = sorted({d.metadata.get("source_stem", "?") for d in docs}) if docs else []
    audit(
        "rag_generate_done",
        kind="rag",
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        patient_id=pid,
        query_snippet=truncate(state.get("query") or ""),
        answer_chars=len(answer),
        retrieved_count=len(docs),
        source_stems=stems,
        controlled_response=False,
    )
    return {"answer": answer, "generation_mode": "grounded_answer"}


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
    if any(term in query for term in ("ola", "oi", "bom dia", "boa tarde", "boa noite")):
        answer = await _stream_answer(state, settings, mode="direct")
    else:
        answer = await _stream_answer(state, settings, mode="direct")
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
    return {"answer": answer, "generation_mode": "direct_answer"}


async def _generate_insufficient_context(state: ChatRAGState, settings: Settings) -> dict:
    """Gera resposta de insuficiência de contexto com streaming."""
    pid = state.get("patient_id") or None
    t0 = time.perf_counter()
    answer = await _stream_answer(state, settings, mode="insufficient")
    structured = state.get("structured_terms") or {}
    rerank_result = state.get("rerank_result") or {}
    disease = structured.get("diretriz") or structured.get("disease") or "a condição solicitada"
    reason = rerank_result.get("insufficiency_reason") or state.get("insufficiency_reason") or "contexto recuperado insuficiente"
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
    return {"answer": answer, "generation_mode": "insufficient_context"}


async def generate_node(state: ChatRAGState, settings: Settings) -> dict:
    """Nó público único de geração: escolhe a estratégia pelo `generation_mode`."""
    mode = str(state.get("generation_mode") or "grounded_answer")
    if mode == "direct_answer":
        return await _generate_direct_answer(state, settings)
    if mode == "insufficient_context":
        return await _generate_insufficient_context(state, settings)
    return await _generate_grounded_answer(state, settings)
