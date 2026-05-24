"""Composable RAG pipeline services shared by chat graph and inspector."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from functools import lru_cache
import json
from typing import Any, Protocol

import httpx
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field, ValidationError

from assistente_medico_api.config import Settings, resolve_chroma_persist_dir
from assistente_medico_api.graph.clinical_query_understanding import (
    classify_clinical_intent,
    normalize_text_for_match,
)
from assistente_medico_api.graph.rag_enhancement import (
    _as_list,
    build_audit_payload,
    document_audit_record,
    expand_query_with_conitec_catalog,
    load_local_conitec_catalog,
    rerank_documents,
)

PIPELINE_VERSION = "separated_nodes_v2"
CONTEXT_SUFFICIENT = "sufficient"
CONTEXT_PARTIAL = "partial"
CONTEXT_INSUFFICIENT = "insufficient"


class ConversationMemoryStore(Protocol):
    """Minimal persistence contract for conversation memory."""

    def load(self, conversation_id: str) -> dict[str, Any] | None: ...

    def save(self, conversation_id: str, memory_update: dict[str, Any]) -> None: ...


class InMemoryConversationMemoryStore:
    """Process-local memory store used until a database adapter is wired."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    def load(self, conversation_id: str) -> dict[str, Any] | None:
        value = self._data.get(conversation_id)
        return deepcopy(value) if value else None

    def save(self, conversation_id: str, memory_update: dict[str, Any]) -> None:
        current = deepcopy(self._data.get(conversation_id) or {})
        turns = list(current.get("turns") or [])
        turns.extend(memory_update.get("turns") or [])
        if len(turns) > 20:
            turns = turns[-20:]
        current.update({k: v for k, v in memory_update.items() if k != "turns"})
        current["turns"] = turns
        current["updated_at"] = _utc_now()
        self._data[conversation_id] = current


MEMORY_STORE = InMemoryConversationMemoryStore()


class LLMRankedDocument(BaseModel):
    doc_id: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class LLMRerankResult(BaseModel):
    ranked_documents: list[LLMRankedDocument] = Field(default_factory=list)
    context_quality: str = CONTEXT_PARTIAL
    insufficiency_reason: str | None = None


@lru_cache(maxsize=1)
def cached_conitec_catalog() -> dict:
    return load_local_conitec_catalog()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _settings_config(settings: Settings) -> dict[str, Any]:
    try:
        persist_dir = str(resolve_chroma_persist_dir(settings))
    except Exception:
        persist_dir = str(getattr(settings, "chroma_persist_dir", "") or "")
    return {
        "pipeline_version": getattr(settings, "rag_pipeline_version", PIPELINE_VERSION),
        "chroma_persist_dir": persist_dir,
        "chroma_collection": settings.chroma_collection,
        "ollama_embed_model": settings.ollama_embed_model,
        "ollama_chat_model": settings.ollama_chat_model,
        "rag_use_llm_rerank": settings.rag_use_llm_rerank,
        "rag_llm_rerank_top_n": settings.rag_llm_rerank_top_n,
        "rag_max_retrieve_attempts": getattr(settings, "rag_max_retrieve_attempts", 2),
    }


def _audit_base(state: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    trace = deepcopy(state.get("audit_trace") or {})
    trace.setdefault("pipeline_version", PIPELINE_VERSION)
    trace.setdefault("steps", [])
    if settings is not None:
        trace.setdefault("config", _settings_config(settings))
    return trace


def append_audit_step(
    state: dict[str, Any],
    *,
    node: str,
    input_summary: dict[str, Any] | None = None,
    output_summary: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    trace = _audit_base(state, settings)
    trace["steps"].append(
        {
            "node": node,
            "timestamp": _utc_now(),
            "input_summary": input_summary or {},
            "output_summary": output_summary or {},
            "warnings": warnings or [],
        }
    )
    return trace


def format_source_label(doc: Document, index: int | None = None) -> str:
    meta = doc.metadata
    diretriz = meta.get("diretriz") or meta.get("disease") or meta.get("source_stem", "?")
    section = meta.get("section")
    p0 = meta.get("page_start", "?")
    p1 = meta.get("page_end", "?")
    body = f"PCDT {diretriz} - {section} (pp. {p0}-{p1})" if section else f"PCDT {diretriz} (pp. {p0}-{p1})"
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


def _history_transcript(turns: list[dict[str, Any]], *, limit: int = 8) -> str:
    lines: list[str] = []
    for turn in turns[-limit:]:
        role = "Usuário" if turn.get("role") == "user" else "Assistente"
        content = str(turn.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _last_structured_terms_from_state(state: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [
        state.get("structured_terms"),
        (state.get("rewrite_result") or {}).get("structured_terms"),
        (state.get("memory_result") or {}).get("last_structured_terms"),
    ]
    for item in candidates:
        if isinstance(item, dict) and item:
            return deepcopy(item)
    return None


def run_load_memory(
    state: dict[str, Any],
    *,
    store: ConversationMemoryStore | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    memory_store = store or MEMORY_STORE
    conversation_id = state.get("conversation_id")
    history = list(state.get("chat_history") or state.get("messages") or [])
    persisted = memory_store.load(str(conversation_id)) if conversation_id else None

    persisted_turns = list((persisted or {}).get("turns") or [])
    turns = persisted_turns + history
    last_structured = _last_structured_terms_from_state(state) or deepcopy((persisted or {}).get("last_structured_terms") or {})
    last_disease = str(last_structured.get("diretriz") or last_structured.get("disease") or "").strip() or None
    last_intent = str(last_structured.get("intent") or "").strip() or None
    source = "state" if history else "database" if persisted else "empty"
    memory_result = {
        "conversation_id": conversation_id,
        "history_available": bool(turns),
        "turns": turns[-20:],
        "history_transcript": _history_transcript(turns),
        "conversation_summary": (persisted or {}).get("summary") or "",
        "summary": (persisted or {}).get("summary") or "",
        "last_structured_terms": last_structured or None,
        "last_disease": last_disease,
        "last_intent": last_intent,
        "last_sources": (persisted or {}).get("last_sources") or [],
        "source": source,
    }
    audit_trace = append_audit_step(
        state,
        node="load_memory",
        output_summary={
            "history_available": memory_result["history_available"],
            "turn_count": len(memory_result["turns"]),
            "last_disease": last_disease,
            "source": source,
        },
        settings=settings,
    )
    return {
        "memory_result": memory_result,
        "memory_context": memory_result,
        "audit_trace": audit_trace,
    }


def _is_simple_direct(text: str) -> bool:
    norm = normalize_text_for_match(text)
    return norm in {
        "oi",
        "ola",
        "olá",
        "bom dia",
        "boa tarde",
        "boa noite",
        "obrigado",
        "obrigada",
        "quem e voce",
        "quem é voce",
        "quem é você",
    }


def run_search_router(
    query: str,
    memory_result: dict | str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    del settings
    text = (query or "").strip()
    memory = memory_result if isinstance(memory_result, dict) else {}
    if not text:
        decision = {
            "search_needed": False,
            "question_type": "unsupported",
            "reason": "pergunta vazia",
            "confidence": 1.0,
            "method": "semantic",
        }
    elif _is_simple_direct(text):
        decision = {
            "search_needed": False,
            "question_type": "smalltalk",
            "reason": "interação simples que não solicita evidência PCDT",
            "confidence": 0.9,
            "method": "semantic",
        }
    else:
        intent = classify_clinical_intent(text)
        has_follow_up_memory = bool(memory.get("last_structured_terms") or memory.get("last_disease"))
        follow_up_shape = normalize_text_for_match(text).startswith(("e ", "e os ", "e as ", "qual ", "quais "))
        search_needed = True
        question_type = "follow_up_question" if has_follow_up_memory and follow_up_shape else "clinical_question"
        if intent.get("intent") and intent.get("intent") != "geral":
            question_type = "protocol_query"
        decision = {
            "search_needed": search_needed,
            "question_type": question_type,
            "reason": "pergunta potencialmente clínica; buscar PCDT por política conservadora",
            "confidence": max(0.7, float(intent.get("confidence") or 0.0)),
            "method": "semantic",
        }
    return {"search_needed": bool(decision["search_needed"]), "router_result": decision, "router_decision": decision}


def run_rewrite_query(
    query: str,
    memory_result: dict | str | None,
    settings: Settings,
) -> dict[str, Any]:
    del settings
    original_query = (query or "").strip()
    memory = memory_result if isinstance(memory_result, dict) else {}
    catalog = cached_conitec_catalog()

    first_expansion = expand_query_with_conitec_catalog(original_query, catalog, max_terms=10)
    first_structured = first_expansion.get("structured_terms") or {}
    resolved_query = original_query
    last_structured = memory.get("last_structured_terms") or {}
    last_disease = str(last_structured.get("diretriz") or last_structured.get("disease") or "").strip()
    current_disease = str(first_structured.get("diretriz") or first_structured.get("disease") or "").strip()
    if last_disease and not current_disease:
        resolved_query = f"{original_query} para {last_disease}".strip()

    expansion = first_expansion if resolved_query == original_query else expand_query_with_conitec_catalog(resolved_query, catalog, max_terms=10)
    structured = expansion.get("structured_terms") or {}
    understanding = expansion.get("clinical_understanding") or {}
    expanded_query = str(expansion.get("expanded_query") or resolved_query).strip()
    rewrite_result = {
        "original_query": original_query,
        "resolved_query": resolved_query,
        "retrieval_query": expanded_query,
        "expanded_query": expanded_query,
        "structured_terms": structured,
        "clinical_understanding": understanding,
        "linked_entities": structured.get("linked_entities") or understanding.get("linked_entities") or [],
        "catalog_candidates": structured.get("catalog_candidates") or understanding.get("catalog_candidates") or [],
        "confidence": float(structured.get("confidence") or 0.0),
    }
    return {
        "rewrite_result": rewrite_result,
        "retrieval_query": rewrite_result["retrieval_query"],
        "expanded_query": rewrite_result["expanded_query"],
        "structured_terms": rewrite_result["structured_terms"],
        "clinical_understanding": rewrite_result["clinical_understanding"],
        "linked_entities": rewrite_result["linked_entities"],
        "catalog_candidates": rewrite_result["catalog_candidates"],
        "query_expansion": expansion,
    }


def _metadata_filter(structured_terms: dict[str, Any]) -> dict[str, Any] | None:
    disease_norm = normalize_text_for_match(structured_terms.get("disease_normalized") or "")
    confidence = float(structured_terms.get("confidence") or 0.0)
    if disease_norm and confidence >= 0.84:
        return {"disease_normalized": disease_norm}
    return None


def _with_dense_metadata(pairs: list[Any], *, attempt: int) -> list[Document]:
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
                "retrieve_attempt": attempt,
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
    filter_applied = metadata_filter is not None
    fallback_to_unfiltered = False
    fallback_reason = None
    try:
        pairs = store.similarity_search_with_score(query, k=k, filter=metadata_filter)
    except Exception as exc:
        fallback_to_unfiltered = bool(metadata_filter)
        fallback_reason = str(exc)[:240]
        pairs = store.similarity_search_with_score(query, k=k)
        metadata_filter = None
    candidate_docs = _with_dense_metadata(list(pairs), attempt=retrieve_attempt)
    retrieve_result = {
        "attempt": retrieve_attempt,
        "query": query,
        "metadata_filter": metadata_filter,
        "candidate_docs": candidate_docs,
        "candidate_count": len(candidate_docs),
        "filter_applied": filter_applied,
        "fallback_to_unfiltered": fallback_to_unfiltered,
        "fallback_reason": fallback_reason,
        "debug": {
            "k": k,
            "collection": settings.chroma_collection,
            "persist_dir": str(resolve_chroma_persist_dir(settings)),
            "embedding_model": settings.ollama_embed_model,
        },
    }
    return {
        "candidate_docs": candidate_docs,
        "retrieve_attempt": retrieve_attempt,
        "retrieve_result": retrieve_result,
        "retrieve_debug": {
            "query_sent_to_chroma": query,
            "k": k,
            "metadata_filter": metadata_filter,
            "candidate_count": len(candidate_docs),
            "filter_applied": filter_applied,
            "fallback_to_unfiltered": fallback_to_unfiltered,
            "fallback_reason": fallback_reason,
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


def _doc_signature(doc: Document) -> tuple[Any, ...]:
    meta = doc.metadata or {}
    return (
        getattr(doc, "id", None),
        meta.get("source_stem"),
        meta.get("page_start"),
        meta.get("page_end"),
        meta.get("section"),
    )


def _extract_first_json_object(raw: str) -> dict[str, Any]:
    start = raw.find("{")
    if start < 0:
        raise ValueError("LLM rerank did not return JSON")
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(raw)):
        ch = raw[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                data = json.loads(raw[start : idx + 1])
                if not isinstance(data, dict):
                    raise ValueError("LLM rerank JSON root is not object")
                return data
    raise ValueError("LLM rerank JSON object is incomplete")


async def _llm_rerank(
    *,
    query: str,
    expanded_query: str,
    structured_terms: dict[str, Any],
    docs: list[Document],
    settings: Settings,
) -> LLMRerankResult:
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
        "ranked_documents, context_quality e insufficiency_reason. "
        "Não selecione documentos de doença/diretriz diferente da detectada."
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
    data = _extract_first_json_object(str(raw))
    return LLMRerankResult.model_validate(data)


def _rank_heuristically(
    *,
    query: str,
    expanded_query: str,
    structured_terms: dict[str, Any],
    clinical_understanding: dict[str, Any],
    docs: list[Document],
    settings: Settings,
) -> list[Document]:
    return rerank_documents(
        query,
        {
            "expanded_query": expanded_query,
            "structured_terms": structured_terms,
            "clinical_understanding": clinical_understanding,
        },
        [(doc, doc.metadata.get("dense_score")) for doc in docs],
        final_k=int(settings.rag_retrieve_final_k),
    )


async def run_rerank_and_validate_context(
    *,
    query: str,
    expanded_query: str,
    structured_terms: dict[str, Any],
    clinical_understanding: dict[str, Any],
    candidate_docs: list[Document],
    settings: Settings,
) -> dict[str, Any]:
    disease_required = bool(structured_terms.get("disease") or structured_terms.get("diretriz"))
    preferred_sections = _as_list(structured_terms.get("preferred_sections"))
    removed_docs = []
    compatible_docs: list[Document] = []
    for idx, doc in enumerate(candidate_docs, start=1):
        if disease_required and not _matches_structured_disease(doc, structured_terms):
            removed_docs.append({"rank": idx, "reason": "disease_mismatch", "document": document_audit_record(doc, idx)})
        else:
            compatible_docs.append(doc)

    llm_debug: dict[str, Any] = {"used": False}
    selected_docs: list[Document] = []
    if compatible_docs and settings.rag_use_llm_rerank:
        try:
            llm_result = await _llm_rerank(
                query=query,
                expanded_query=expanded_query,
                structured_terms=structured_terms,
                docs=compatible_docs,
                settings=settings,
            )
            id_to_doc = {f"doc_{idx}": doc for idx, doc in enumerate(compatible_docs[: int(settings.rag_llm_rerank_top_n)], start=1)}
            selected_docs = [id_to_doc[item.doc_id] for item in llm_result.ranked_documents if item.doc_id in id_to_doc]
            selected_docs = selected_docs[: max(1, int(settings.rag_retrieve_final_k))]
            llm_debug = {"used": True, "result": llm_result.model_dump()}
            if not selected_docs:
                raise ValueError("LLM rerank returned no selectable documents")
        except (ValidationError, Exception) as exc:
            llm_debug = {"used": True, "error": str(exc), "fallback": "heuristic"}
            selected_docs = _rank_heuristically(
                query=query,
                expanded_query=expanded_query,
                structured_terms=structured_terms,
                clinical_understanding=clinical_understanding,
                docs=compatible_docs,
                settings=settings,
            )
    elif compatible_docs:
        selected_docs = _rank_heuristically(
            query=query,
            expanded_query=expanded_query,
            structured_terms=structured_terms,
            clinical_understanding=clinical_understanding,
            docs=compatible_docs,
            settings=settings,
        )

    found_diseases = sorted({str((doc.metadata or {}).get("disease") or (doc.metadata or {}).get("diretriz") or "") for doc in compatible_docs if doc.metadata})
    found_sections = sorted({str((doc.metadata or {}).get("section") or (doc.metadata or {}).get("header_1") or "") for doc in selected_docs if doc.metadata})
    has_preferred_section = (not preferred_sections) or any(_section_match(doc, structured_terms) for doc in selected_docs)
    context_quality = CONTEXT_SUFFICIENT
    failure_type = None
    insufficiency_reason = None

    if not candidate_docs:
        context_quality = CONTEXT_INSUFFICIENT
        failure_type = "no_documents"
        insufficiency_reason = "nenhum candidato recuperado"
    elif disease_required and not compatible_docs:
        context_quality = CONTEXT_INSUFFICIENT
        failure_type = "wrong_disease"
        insufficiency_reason = "documentos recuperados não correspondem à doença/diretriz detectada"
    elif not selected_docs:
        context_quality = CONTEXT_INSUFFICIENT
        failure_type = "no_selected_documents"
        insufficiency_reason = "rerank não selecionou documentos relevantes"
    elif preferred_sections and not has_preferred_section:
        context_quality = CONTEXT_PARTIAL
        failure_type = "missing_preferred_section"
        insufficiency_reason = "seção preferencial não encontrada; contexto parcialmente suficiente"

    context_sufficient = context_quality == CONTEXT_SUFFICIENT
    sources = [format_source_label(doc, i) for i, doc in enumerate(selected_docs, start=1)]
    selected_audit = [document_audit_record(doc, i) for i, doc in enumerate(selected_docs, start=1)]
    rerank_result = {
        "selected_docs": selected_docs,
        "context_quality": context_quality,
        "context_sufficient": context_sufficient,
        "failure_type": failure_type,
        "insufficiency_reason": insufficiency_reason,
        "expected_disease": structured_terms.get("diretriz") or structured_terms.get("disease"),
        "expected_sections": preferred_sections,
        "found_diseases": found_diseases,
        "found_sections": found_sections,
        "llm_rerank_used": bool(llm_debug.get("used")),
        "debug": {
            "candidate_count": len(candidate_docs),
            "after_disease_filter": len(compatible_docs),
            "removed_documents": removed_docs,
            "selected_documents": selected_audit,
            "has_preferred_section": has_preferred_section,
            "llm_rerank": llm_debug,
        },
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
        "rerank_result": rerank_result,
        "rerank_debug": rerank_result["debug"],
        "rag_audit_payload": audit_payload,
    }


def route_context_quality(state: dict[str, Any]) -> str:
    quality = (state.get("rerank_result") or {}).get("context_quality")
    if quality == CONTEXT_SUFFICIENT or state.get("context_sufficient") is True:
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


def merge_candidate_attempts(previous: list[Document], current: list[Document]) -> list[Document]:
    seen = {_doc_signature(doc) for doc in previous}
    merged = list(previous)
    for doc in current:
        sig = _doc_signature(doc)
        if sig not in seen:
            merged.append(doc)
            seen.add(sig)
    return merged


def build_pipeline_audit(
    state: dict[str, Any],
    *,
    generate_mode: str | None = None,
    guardrail: dict | None = None,
) -> dict[str, Any]:
    payload = deepcopy(state.get("rag_audit_payload") or {"query": state.get("query") or ""})
    attempts = list(payload.get("retrieve_attempts") or [])
    retrieve_result = state.get("retrieve_result") or {}
    if retrieve_result and not any(item.get("attempt") == retrieve_result.get("attempt") for item in attempts):
        attempts.append(
            {
                "attempt": retrieve_result.get("attempt"),
                "query": retrieve_result.get("query"),
                "candidate_count": retrieve_result.get("candidate_count"),
                "metadata_filter": retrieve_result.get("metadata_filter"),
                "fallback_to_unfiltered": retrieve_result.get("fallback_to_unfiltered"),
            }
        )
    payload.update(
        {
            "query": state.get("query") or payload.get("query") or "",
            "pipeline_version": PIPELINE_VERSION,
            "memory_result": state.get("memory_result") or payload.get("memory_result") or {},
            "router_result": state.get("router_result") or payload.get("router_result") or {},
            "rewrite": state.get("rewrite_result") or payload.get("rewrite") or {},
            "retrieve_attempts": attempts,
            "rerank": state.get("rerank_result") or payload.get("rerank") or {},
            "audit_trace": state.get("audit_trace") or payload.get("audit_trace") or {},
        }
    )
    if generate_mode:
        payload["generate_mode"] = generate_mode
    if guardrail:
        payload["guardrail"] = guardrail
    return payload


def run_save_memory(
    state: dict[str, Any],
    *,
    store: ConversationMemoryStore | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    memory_store = store or MEMORY_STORE
    conversation_id = state.get("conversation_id") or (state.get("memory_result") or {}).get("conversation_id")
    structured = state.get("structured_terms") or (state.get("rewrite_result") or {}).get("structured_terms") or {}
    generation = state.get("generation_result") or {}
    rerank = state.get("rerank_result") or {}
    answer = state.get("answer") or generation.get("answer") or ""
    if conversation_id:
        memory_store.save(
            str(conversation_id),
            {
                "turns": [
                    {"role": "user", "content": state.get("query") or ""},
                    {"role": "assistant", "content": answer},
                ],
                "last_structured_terms": structured,
                "last_disease": structured.get("diretriz") or structured.get("disease"),
                "last_intent": structured.get("intent"),
                "last_sources": state.get("sources") or [],
                "context_quality": rerank.get("context_quality"),
                "audit_id": state.get("audit_id"),
                "summary": (state.get("memory_result") or {}).get("summary") or "",
            },
        )
    audit_trace = append_audit_step(
        state,
        node="save_memory",
        input_summary={"conversation_id": conversation_id},
        output_summary={"saved": bool(conversation_id), "disease": structured.get("disease") or structured.get("diretriz")},
        settings=settings,
    )
    return {"memory_saved": bool(conversation_id), "audit_trace": audit_trace}


async def run_full_graph_debug(
    *,
    query: str,
    settings: Settings,
    store: Chroma,
    conversation_id: str | None = None,
    chat_history: list | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "query": query,
        "conversation_id": conversation_id,
        "chat_history": chat_history or [],
        "retrieve_attempt": 1,
        "max_retrieve_attempts": int(getattr(settings, "rag_max_retrieve_attempts", 2)),
    }
    state.update(run_load_memory(state, settings=settings))
    state.update(run_search_router(query, state.get("memory_result"), settings))
    if not state.get("search_needed"):
        state["generation_result"] = {"mode": "direct", "answer": ""}
        return {"state": state, "audit": build_pipeline_audit(state), "route": "direct"}

    state.update(run_rewrite_query(query, state.get("memory_result"), settings))
    retrieve = run_retrieve(
        expanded_query=state.get("expanded_query") or query,
        structured_terms=state.get("structured_terms") or {},
        store=store,
        settings=settings,
        retrieve_attempt=1,
    )
    state.update(retrieve)
    state["audit_trace"] = append_audit_step(
        state,
        node="retrieve_attempt_1",
        output_summary=retrieve.get("retrieve_result") or {},
        settings=settings,
    )
    rerank = await run_rerank_and_validate_context(
        query=query,
        expanded_query=state.get("expanded_query") or query,
        structured_terms=state.get("structured_terms") or {},
        clinical_understanding=state.get("clinical_understanding") or {},
        candidate_docs=state.get("candidate_docs") or [],
        settings=settings,
    )
    state.update(rerank)
    state["audit_trace"] = append_audit_step(
        state,
        node="rerank_and_validate_context",
        output_summary=state.get("rerank_result") or {},
        settings=settings,
    )
    if route_context_quality(state) == "fallback_retrieve":
        state["retrieve_attempt"] = 2
        fallback = run_retrieve(
            expanded_query=state.get("expanded_query") or query,
            structured_terms=state.get("structured_terms") or {},
            store=store,
            settings=settings,
            retrieve_attempt=2,
            fallback_query=build_fallback_query(query, state.get("structured_terms") or {}),
        )
        previous = list(state.get("candidate_docs") or [])
        current = list(fallback.get("candidate_docs") or [])
        state["candidate_docs_attempt_1"] = previous
        state["candidate_docs_attempt_2"] = current
        fallback["candidate_docs"] = merge_candidate_attempts(previous, current)
        state.update(fallback)
        state["audit_trace"] = append_audit_step(
            state,
            node="fallback_retrieve_attempt_2",
            output_summary=fallback.get("retrieve_result") or {},
            settings=settings,
        )
        rerank = await run_rerank_and_validate_context(
            query=query,
            expanded_query=state.get("expanded_query") or query,
            structured_terms=state.get("structured_terms") or {},
            clinical_understanding=state.get("clinical_understanding") or {},
            candidate_docs=state.get("candidate_docs") or [],
            settings=settings,
        )
        state.update(rerank)
        state["audit_trace"] = append_audit_step(
            state,
            node="rerank_and_validate_context",
            output_summary=state.get("rerank_result") or {},
            settings=settings,
        )
    route = route_context_quality(state)
    state["generation_result"] = {
        "mode": "grounded" if route == "generate_grounded" else "insufficient",
        "answer": "",
    }
    return {"state": state, "audit": build_pipeline_audit(state), "route": route}
