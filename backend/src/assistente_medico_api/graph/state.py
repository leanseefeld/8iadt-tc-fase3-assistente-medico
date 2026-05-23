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
    chat_history: list[ChatHistoryTurnState]
    retrieval_query: str
    retrieved_docs: list[Document]
    sources: list[str]
    reasoning_steps: list[str]
    query_expansion: dict
    clinical_understanding: dict
    rag_audit_payload: dict
    audit_id: str
    answer: str
    guardrail_status: str  # "safe" | "warned" | "blocked" | "regenerated"
    guardrail_reason: str
