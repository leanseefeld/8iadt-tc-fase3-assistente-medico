"""Estado do grafo de chat RAG."""

from __future__ import annotations

from typing import Literal, TypedDict

from langchain_core.documents import Document

# Limite de itens em chat_history (cada item = um turno user ou assistant).
CHAT_HISTORY_MAX_ITEMS = 20


class ChatHistoryTurnState(TypedDict):
    """Turno de conversa anterior, serializável no estado do grafo."""

    role: Literal["user", "assistant"]
    content: str


class ChatRAGState(TypedDict, total=False):
    """Estado passado entre nós."""

    query: str
    patient_id: str
    conversation_id: str | None
    chat_history: list[ChatHistoryTurnState]
    search_needed: bool
    router_decision: dict
    generation_mode: Literal["grounded_answer", "direct_answer", "insufficient_context"]
    retrieval_query: str
    expanded_query: str
    structured_terms: dict
    clinical_understanding: dict
    linked_entities: list
    catalog_candidates: list
    query_expansion: dict
    candidate_docs: list[Document]
    retrieved_docs: list[Document]
    retrieve_result: dict
    retrieve_attempt: int
    max_retrieve_attempts: int
    retrieve_debug: dict
    rerank_decision: dict
    rerank_result: dict
    rerank_debug: dict
    context_sufficient: bool
    insufficiency_reason: str | None
    sources: list[str]
    reasoning_steps: list[str]
    generation_result: dict
    answer: str
    guardrail_result: dict
    guardrail_status: str  # "safe" | "warned" | "blocked" | "regenerated"
    guardrail_reason: str
    patient_context: str
    generate_llm_input: list[dict]
    generate_llm_output: str
