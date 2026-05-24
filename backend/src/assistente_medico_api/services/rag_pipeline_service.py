"""Composable RAG pipeline services shared by chat graph and inspector."""

from __future__ import annotations

from functools import lru_cache
import json
import re
from typing import Any

import httpx
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.clinical_query_understanding import normalize_text_for_match
from assistente_medico_api.graph.rag_enhancement import (
    _as_list,
    build_audit_payload,
    document_audit_record,
    expand_query_with_conitec_catalog,
    load_local_conitec_catalog,
    rerank_documents,
)

_RAG_HINT_RE = re.compile(
    r"\b("
    r"pcdt|protocolo|diretriz|criteri[oa]s?|inclus[aã]o|exclus[aã]o|"
    r"diagn[oó]stic[oa]|tratamento|monitoramento|seguimento|cid|"
    r"medicamento|f[aá]rmaco|conduta|reconhecer|suspeita|manejo"
    r")\b",
    re.IGNORECASE,
)
_DIRECT_HINT_RE = re.compile(r"\b(oi|ol[aá]|obrigad[oa]|bom dia|boa tarde|boa noite|quem [ée] voc[eê])\b", re.IGNORECASE)


@lru_cache(maxsize=1)
def cached_conitec_catalog() -> dict:
    return load_local_conitec_catalog()


def format_source_label(doc: Document, index: int | None = None) -> str:
    """Human-readable source label aligned with prompt document ranks."""
    meta = doc.metadata
    diretriz = meta.get("diretriz") or meta.get("disease") or meta.get("source_stem", "?")
    section = meta.get("section")
    p0 = meta.get("page_start", "?")
    p1 = meta.get("page_end", "?")
    if section:
        body = f"PCDT {diretriz} - {section} (pp. {p0}-{p1})"
    else:
        body = f"PCDT {diretriz} (pp. {p0}-{p1})"
    return f"[{index}] {body}" if index is not None else body


def _build_llm(settings: Settings, *, temperature: float = 0.0) -> ChatOllama:
    timeout = httpx.Timeout(settings.llm_stream_timeout_s, connect=10.0)
    return ChatOllama(
        model=settings.ollama_chat_model,
        base_url=settings.ollama_base_url,
        temperature=temperature,
        async_client_kwargs={"timeout": timeout},
        client_kwargs={"timeout": timeout},
    )


def _audit_base(state: dict[str, Any]) -> dict[str, Any]:
    return dict(state.get("rag_audit_payload") or {"query": state.get("query") or ""})


def merge_audit(state: dict[str, Any], **updates: Any) -> dict[str, Any]:
    payload = _audit_base(state)
    payload.update(updates)
    return payload


def run_load_memory(state: dict[str, Any]) -> dict[str, Any]:
    history = list(state.get("chat_history") or [])
    user_questions = [
        str(turn.get("content") or "").strip()
        for turn in history
        if turn.get("role") == "user" and str(turn.get("content") or "").strip()
    ]
    last_disease = ""
    for turn in reversed(history):
        text = str(turn.get("content") or "")
        match = re.search(r"(Síndrome de Guillain-Barré|Lúpus Eritematoso Sistêmico|Insuficiência Adrenal)", text, re.I)
        if match:
            last_disease = match.group(1)
            break
    memory_context = {
        "last_user_questions": user_questions[-3:],
        "last_detected_disease": last_disease,
        "summary": "",
    }
    return {
        "memory_context": memory_context,
        "rag_audit_payload": merge_audit(state, memory_context=memory_context),
    }


def run_search_router(query: str, memory_context: dict | str | None = None) -> dict[str, Any]:
    text = (query or "").strip()
    if not text:
        decision = {
            "search_needed": False,
            "question_type": "unsupported",
            "reason": "pergunta vazia",
            "confidence": 1.0,
        }
    elif _RAG_HINT_RE.search(text):
        decision = {
            "search_needed": True,
            "question_type": "protocol_query",
            "reason": "pergunta solicita informação clínica/protocolo baseada em PCDT",
            "confidence": 0.9,
        }
    elif _DIRECT_HINT_RE.fullmatch(normalize_text_for_match(text)) or _DIRECT_HINT_RE.search(text):
        decision = {
            "search_needed": False,
            "question_type": "smalltalk",
            "reason": "interação simples que não solicita evidência PCDT",
            "confidence": 0.86,
        }
    elif isinstance(memory_context, dict) and memory_context.get("last_detected_disease"):
        decision = {
            "search_needed": True,
            "question_type": "follow_up_question",
            "reason": "pergunta pode depender da condição clínica mencionada no histórico",
            "confidence": 0.72,
        }
    else:
        decision = {
            "search_needed": True,
            "question_type": "clinical_question",
            "reason": "pergunta potencialmente clínica; usar RAG por segurança",
            "confidence": 0.68,
        }
    return {"search_needed": bool(decision["search_needed"]), "router_decision": decision}


def run_rewrite_query(query: str, memory_context: dict | str | None, settings: Settings) -> dict[str, Any]:
    del settings
    base_query = (query or "").strip()
    if isinstance(memory_context, dict):
        last_disease = str(memory_context.get("last_detected_disease") or "").strip()
        if last_disease and normalize_text_for_match(last_disease) not in normalize_text_for_match(base_query):
            base_query = f"{base_query} {last_disease}".strip()

    catalog = cached_conitec_catalog()
    expansion = expand_query_with_conitec_catalog(base_query, catalog, max_terms=10)
    structured = expansion.get("structured_terms") or {}
    understanding = expansion.get("clinical_understanding") or {}
    expanded_query = str(expansion.get("expanded_query") or base_query).strip()
    return {
        "retrieval_query": expanded_query,
        "expanded_query": expanded_query,
        "structured_terms": structured,
        "clinical_understanding": understanding,
        "linked_entities": structured.get("linked_entities") or understanding.get("linked_entities") or [],
        "catalog_candidates": structured.get("catalog_candidates") or understanding.get("catalog_candidates") or [],
        "query_expansion": expansion,
    }


def _metadata_filter(structured_terms: dict[str, Any]) -> dict[str, Any] | None:
    disease_norm = normalize_text_for_match(structured_terms.get("disease_normalized") or "")
    confidence = float(structured_terms.get("confidence") or 0.0)
    if disease_norm and confidence >= 0.84:
        return {"disease_normalized": disease_norm}
    return None


def _with_dense_metadata(pairs: list[Any]) -> list[Document]:
    docs: list[Document] = []
    total = max(1, len(pairs))
    for rank, item in enumerate(pairs, start=1):
        doc = item[0] if isinstance(item, tuple) else item
        score = item[1] if isinstance(item, tuple) and len(item) > 1 else None
        meta = dict(getattr(doc, "metadata", {}) or {})
        meta.update(
            {
                "dense_score": float(score) if score is not None else None,
                "dense_rank": rank,
                "dense_rank_score": round(1.0 - ((rank - 1) / total), 6),
            }
        )
        docs.append(Document(page_content=str(getattr(doc, "page_content", "") or ""), metadata=meta, id=getattr(doc, "id", None)))
    return docs


def run_retrieve(
    *,
    expanded_query: str,
    structured_terms: dict[str, Any],
    store: Chroma,
    settings: Settings,
    retrieve_attempt: int,
    fallback_query: str | None = None,
) -> dict[str, Any]:
    query = (fallback_query or expanded_query or "").strip()
    k = max(1, int(getattr(settings, "rag_retrieve_candidates_k", 30)))
    metadata_filter = _metadata_filter(structured_terms)
    try:
        pairs = store.similarity_search_with_score(query, k=k, filter=metadata_filter)
    except Exception:
        pairs = store.similarity_search_with_score(query, k=k)
        metadata_filter = None
    candidate_docs = _with_dense_metadata(list(pairs))
    return {
        "candidate_docs": candidate_docs,
        "retrieve_attempt": retrieve_attempt,
        "retrieve_debug": {
            "query_sent_to_chroma": query,
            "k": k,
            "metadata_filter": metadata_filter,
            "candidate_count": len(candidate_docs),
        },
    }


def _doc_disease_norm(doc: Document) -> str:
    meta = dict(doc.metadata or {})
    return normalize_text_for_match(meta.get("disease_normalized") or meta.get("disease") or meta.get("diretriz") or "")


def _matches_structured_disease(doc: Document, structured_terms: dict[str, Any]) -> bool:
    disease_norm = normalize_text_for_match(
        structured_terms.get("disease_normalized") or structured_terms.get("disease") or structured_terms.get("diretriz") or ""
    )
    if not disease_norm:
        return True
    doc_norm = _doc_disease_norm(doc)
    return bool(doc_norm and doc_norm == disease_norm)


def _section_match(doc: Document, structured_terms: dict[str, Any]) -> bool:
    preferred = [normalize_text_for_match(v) for v in _as_list(structured_terms.get("preferred_sections"))]
    if not preferred:
        return False
    meta = dict(doc.metadata or {})
    section = normalize_text_for_match(" ".join(_as_list(meta.get("section")) + _as_list(meta.get("header_1")) + _as_list(meta.get("header_2"))))
    return any(item and item in section for item in preferred)


async def _llm_rerank(
    *,
    query: str,
    expanded_query: str,
    structured_terms: dict[str, Any],
    docs: list[Document],
    settings: Settings,
) -> dict[str, Any]:
    doc_items = []
    for idx, doc in enumerate(docs[: int(settings.rag_llm_rerank_top_n)], start=1):
        meta = dict(doc.metadata or {})
        doc_items.append(
            {
                "doc_id": f"doc_{idx}",
                "rank": idx,
                "disease": meta.get("disease") or meta.get("diretriz"),
                "section": meta.get("section") or meta.get("header_1"),
                "pages": f"{meta.get('page_start', '?')}-{meta.get('page_end', '?')}",
                "snippet": str(doc.page_content or "")[:900],
            }
        )
    system = (
        "Você é um reranker RAG médico. Retorne somente JSON válido com "
        "ranked_documents, context_sufficient e insufficiency_reason."
    )
    human = json.dumps(
        {
            "query": query,
            "expanded_query": expanded_query,
            "structured_terms": structured_terms,
            "candidate_documents": doc_items,
        },
        ensure_ascii=False,
    )
    result = await _build_llm(settings, temperature=0.0).ainvoke([SystemMessage(content=system), HumanMessage(content=human)])
    raw = getattr(result, "content", "") or ""
    if isinstance(raw, list):
        raw = "".join(str(part) for part in raw)
    match = re.search(r"\{.*\}", str(raw), re.DOTALL)
    if not match:
        raise ValueError("LLM rerank did not return JSON")
    data = json.loads(match.group())
    return data if isinstance(data, dict) else {}


async def run_rerank_and_validate_context(
    *,
    query: str,
    expanded_query: str,
    structured_terms: dict[str, Any],
    clinical_understanding: dict[str, Any],
    candidate_docs: list[Document],
    settings: Settings,
) -> dict[str, Any]:
    compatible_docs = [doc for doc in candidate_docs if _matches_structured_disease(doc, structured_terms)]
    disease_required = bool(structured_terms.get("disease") or structured_terms.get("diretriz"))
    filtered_docs = compatible_docs if disease_required else list(candidate_docs)
    llm_debug: dict[str, Any] = {"used": False}
    selected_docs: list[Document]

    if settings.rag_use_llm_rerank and filtered_docs:
        try:
            llm_result = await _llm_rerank(
                query=query,
                expanded_query=expanded_query,
                structured_terms=structured_terms,
                docs=filtered_docs,
                settings=settings,
            )
            llm_debug = {"used": True, "result": llm_result}
            id_to_doc = {f"doc_{idx}": doc for idx, doc in enumerate(filtered_docs[: int(settings.rag_llm_rerank_top_n)], start=1)}
            selected_docs = [
                id_to_doc[item.get("doc_id")]
                for item in llm_result.get("ranked_documents", [])
                if isinstance(item, dict) and item.get("doc_id") in id_to_doc
            ]
            selected_docs = selected_docs[: max(1, int(settings.rag_retrieve_final_k))]
            if not selected_docs:
                raise ValueError("LLM rerank returned no selected docs")
        except Exception as exc:
            llm_debug = {"used": True, "error": str(exc), "fallback": "heuristic"}
            selected_docs = rerank_documents(
                query,
                {"expanded_query": expanded_query, "structured_terms": structured_terms, "clinical_understanding": clinical_understanding},
                [(doc, doc.metadata.get("dense_score")) for doc in filtered_docs],
                final_k=int(settings.rag_retrieve_final_k),
            )
    else:
        selected_docs = rerank_documents(
            query,
            {"expanded_query": expanded_query, "structured_terms": structured_terms, "clinical_understanding": clinical_understanding},
            [(doc, doc.metadata.get("dense_score")) for doc in filtered_docs],
            final_k=int(settings.rag_retrieve_final_k),
        )

    has_disease_doc = (not disease_required) or any(_matches_structured_disease(doc, structured_terms) for doc in selected_docs)
    preferred_sections = _as_list(structured_terms.get("preferred_sections"))
    has_preferred_section = (not preferred_sections) or any(_section_match(doc, structured_terms) for doc in selected_docs)
    context_sufficient = bool(selected_docs and has_disease_doc)
    insufficiency_reason = None
    if not candidate_docs:
        context_sufficient = False
        insufficiency_reason = "nenhum candidato recuperado"
    elif disease_required and not compatible_docs:
        context_sufficient = False
        insufficiency_reason = "documentos recuperados não correspondem à doença/diretriz detectada"
    elif not selected_docs:
        context_sufficient = False
        insufficiency_reason = "rerank não selecionou documentos relevantes"
    elif preferred_sections and not has_preferred_section:
        insufficiency_reason = "seção preferencial não encontrada; contexto parcialmente suficiente"

    sources = [format_source_label(doc, i) for i, doc in enumerate(selected_docs, start=1)]
    rerank_debug = {
        "candidate_count": len(candidate_docs),
        "after_disease_filter": len(filtered_docs),
        "selected_count": len(selected_docs),
        "has_preferred_section": has_preferred_section,
        "llm_rerank": llm_debug,
        "selected_documents": [document_audit_record(doc, i) for i, doc in enumerate(selected_docs, start=1)],
    }
    audit_payload = build_audit_payload(
        question=query,
        expansion={
            "original_query": query,
            "expanded_query": expanded_query,
            "structured_terms": structured_terms,
            "clinical_understanding": clinical_understanding,
        },
        documents=selected_docs,
        retrieval_candidates_k=len(candidate_docs),
        retrieval_final_k=int(settings.rag_retrieve_final_k),
    )
    return {
        "retrieved_docs": selected_docs,
        "sources": sources,
        "context_sufficient": context_sufficient,
        "insufficiency_reason": insufficiency_reason,
        "rerank_debug": rerank_debug,
        "rag_audit_payload": audit_payload,
    }


def route_context_quality(state: dict[str, Any]) -> str:
    if state.get("context_sufficient") is True:
        return "generate_grounded"
    if int(state.get("retrieve_attempt") or 1) < int(state.get("max_retrieve_attempts") or 2):
        return "fallback_retrieve"
    return "generate_insufficient"


def build_fallback_query(query: str, structured_terms: dict[str, Any]) -> str:
    terms = [
        structured_terms.get("diretriz") or structured_terms.get("disease"),
        *_as_list(structured_terms.get("preferred_sections")),
        *_as_list(structured_terms.get("cid10_codes")),
        query,
    ]
    return " ".join(str(term).strip() for term in terms if str(term or "").strip())


def build_pipeline_audit(state: dict[str, Any], *, generate_mode: str | None = None, guardrail: dict | None = None) -> dict[str, Any]:
    payload = _audit_base(state)
    attempts = list(payload.get("retrieve_attempts") or [])
    retrieve_debug = state.get("retrieve_debug") or {}
    if retrieve_debug:
        attempts.append(
            {
                "attempt": state.get("retrieve_attempt"),
                "query": retrieve_debug.get("query_sent_to_chroma"),
                "candidate_count": retrieve_debug.get("candidate_count"),
                "metadata_filter": retrieve_debug.get("metadata_filter"),
            }
        )
    payload.update(
        {
            "query": state.get("query") or payload.get("query") or "",
            "memory_context": state.get("memory_context") or payload.get("memory_context") or {},
            "router_decision": state.get("router_decision") or payload.get("router_decision") or {},
            "rewrite": {
                "retrieval_query": state.get("retrieval_query") or "",
                "expanded_query": state.get("expanded_query") or "",
                "structured_terms": state.get("structured_terms") or {},
                "linked_entities": state.get("linked_entities") or [],
                "catalog_candidates": state.get("catalog_candidates") or [],
            },
            "retrieve_attempts": attempts,
            "rerank": {
                "context_sufficient": state.get("context_sufficient"),
                "insufficiency_reason": state.get("insufficiency_reason"),
                "selected_documents": (state.get("rerank_debug") or {}).get("selected_documents") or [],
            },
        }
    )
    if generate_mode:
        payload["generate_mode"] = generate_mode
    if guardrail:
        payload["guardrail"] = guardrail
    return payload
