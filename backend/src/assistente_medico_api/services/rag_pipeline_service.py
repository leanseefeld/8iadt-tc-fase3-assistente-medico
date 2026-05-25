"""Composable RAG pipeline services shared by chat graph and inspector."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import logging
import uuid
from typing import Any

import httpx
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field, ValidationError

from assistente_medico_api.config import Settings, resolve_chroma_persist_dir
from assistente_medico_api.graph.clinical_entity_resolver import resolve_clinical_entities
from assistente_medico_api.graph.clinical_query_understanding import (
    classify_clinical_intent,
    normalize_text_for_match,
)
from assistente_medico_api.graph.rag_enhancement import (
    _as_list,
    document_audit_record,
    expand_query_with_conitec_catalog,
    load_local_conitec_catalog,
    rerank_documents,
)

CONTEXT_SUFFICIENT = "sufficient"
CONTEXT_PARTIAL = "partial"
CONTEXT_INSUFFICIENT = "insufficient"
_logger = logging.getLogger("assistente_medico.rag")


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


def run_rewrite_query(
    query: str,
    memory_result: dict | str | None,
    settings: Settings,
    *,
    resolved_query: str | None = None,
    rewrite_debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _logger.info("rewrite: start")
    original_query = (query or "").strip()
    memory = memory_result if isinstance(memory_result, dict) else {}
    catalog = cached_conitec_catalog()

    first_expansion = expand_query_with_conitec_catalog(original_query, catalog, max_terms=10)
    first_structured = first_expansion.get("structured_terms") or {}
    final_resolved_query = (resolved_query or "").strip() or original_query
    last_structured = memory.get("last_structured_terms") or {}
    last_disease = str(last_structured.get("diretriz") or last_structured.get("disease") or "").strip()
    current_disease = str(first_structured.get("diretriz") or first_structured.get("disease") or "").strip()
    if not resolved_query and last_disease and not current_disease:
        final_resolved_query = f"{original_query} para {last_disease}".strip()

    expansion = (
        first_expansion
        if final_resolved_query == original_query
        else expand_query_with_conitec_catalog(final_resolved_query, catalog, max_terms=10)
    )
    structured = expansion.get("structured_terms") or {}
    understanding = expansion.get("clinical_understanding") or {}
    _logger.info("rewrite: before_entity_resolver")
    entity_result = resolve_clinical_entities(
        final_resolved_query,
        catalog=catalog,
        intent=understanding.get("intent_result") or {"intent": structured.get("intent"), "confidence": structured.get("confidence")},
        enable_medical_nlp=bool(getattr(settings, "enable_medical_nlp", True)),
        use_medspacy=bool(getattr(settings, "use_medspacy", False)),
    )
    _logger.info(
        "rewrite: after_entity_resolver backend=%s spacy=%s linked_entities=%s",
        entity_result.get("entity_backend"),
        entity_result.get("spacy_used"),
        len(entity_result.get("linked_entities") or []),
    )
    linked_entities = _merge_linked_entities(
        entity_result.get("linked_entities") or [],
        structured.get("linked_entities") or understanding.get("linked_entities") or [],
    )
    catalog_candidates = (
        structured.get("catalog_candidates")
        or understanding.get("catalog_candidates")
        or entity_result.get("catalog_candidates")
        or []
    )
    structured = {**structured, "linked_entities": linked_entities, "catalog_candidates": catalog_candidates}
    understanding = {
        **understanding,
        "linked_entities": linked_entities,
        "catalog_candidates": catalog_candidates,
        "entity_backend": entity_result.get("entity_backend"),
        "spacy_used": entity_result.get("spacy_used"),
    }
    expanded_query = str(expansion.get("expanded_query") or final_resolved_query).strip()
    rewrite_result = {
        "original_query": original_query,
        "resolved_query": final_resolved_query,
        "retrieval_query": expanded_query,
        "expanded_query": expanded_query,
        "structured_terms": structured,
        "clinical_understanding": understanding,
        "linked_entities": linked_entities,
        "catalog_candidates": catalog_candidates,
        "confidence": float(structured.get("confidence") or 0.0),
        "history_transcript_used": memory.get("history_transcript") or "",
        "llm_rewrite_used": bool((rewrite_debug or {}).get("llm_rewrite_used")),
        "rewrite_debug": rewrite_debug or {},
        "spacy_used": entity_result.get("spacy_used"),
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


def _merge_linked_entities(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for group in groups:
        for item in group:
            if not isinstance(item, dict):
                continue
            key = (
                normalize_text_for_match(item.get("text") or ""),
                normalize_text_for_match(item.get("canonical") or ""),
                str(item.get("source") or ""),
            )
            if not key[0] or key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


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
    _logger.info("retrieve: start")
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
    candidate_records = [document_audit_record(doc, i) for i, doc in enumerate(candidate_docs, start=1)]
    retrieve_result = {
        "attempt": retrieve_attempt,
        "query": query,
        "metadata_filter": metadata_filter,
        "candidate_documents": candidate_records,
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
    _logger.info("rerank: start")
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
        "selected_docs": selected_audit,
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
    return {
        "retrieved_docs": selected_docs,
        "sources": sources,
        "context_sufficient": context_sufficient,
        "insufficiency_reason": insufficiency_reason,
        "rerank_result": rerank_result,
        "rerank_debug": rerank_result["debug"],
    }


async def run_full_graph_debug(
    *,
    query: str,
    settings: Settings,
    store: Chroma,
    conversation_id: str | None = None,
    chat_history: list | None = None,
) -> dict[str, Any]:
    from assistente_medico_api.graph.nodes.generate import generate_node
    from assistente_medico_api.graph.nodes.guardrail import guardrail_node
    from assistente_medico_api.graph.nodes.rerank import context_quality_router, rerank_and_validate_context_node
    from assistente_medico_api.graph.nodes.retrieve import retrieve_node
    from assistente_medico_api.graph.nodes.rewrite import rewrite_query_node
    from assistente_medico_api.graph.nodes.router import router_search_needed_node

    state: dict[str, Any] = {
        "query": query,
        "conversation_id": conversation_id,
        "chat_history": chat_history or [],
        "audit_id": str(uuid.uuid4()),
        "retrieve_attempt": 1,
        "max_retrieve_attempts": int(getattr(settings, "rag_max_retrieve_attempts", 2)),
        "retrieved_docs": [],
        "sources": [],
        "reasoning_steps": [],
        "answer": "",
        "generation_mode": "grounded_answer",
    }

    state.update(await router_search_needed_node(state, settings=settings))
    if not state.get("search_needed"):
        state["generation_mode"] = "direct_answer"
        state.update(await generate_node(state, settings))
        state.update(await guardrail_node(state, settings))
        return {"state": state, "audit": {}, "route": "direct"}

    state.update(await rewrite_query_node(state, settings))

    while True:
        state.update(
            retrieve_node(
                state,
                store=store,
                settings=settings,
            )
        )
        state.update(
            await rerank_and_validate_context_node(
                state,
                settings=settings,
            )
        )
        route = context_quality_router(state)
        if route == "retry_retrieve":
            continue
        break

    if state.get("generation_mode") not in {"grounded_answer", "insufficient_context"}:
        state["generation_mode"] = "grounded_answer" if state.get("context_sufficient") else "insufficient_context"
    state.update(await generate_node(state, settings))
    state.update(await guardrail_node(state, settings))
    return {"state": state, "audit": {}, "route": "rag"}
