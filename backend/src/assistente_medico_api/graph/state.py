"""Estado do grafo de chat RAG."""

from __future__ import annotations

from typing import Literal, TypedDict

from langchain_core.documents import Document


class ChatHistoryTurnState(TypedDict):
    """Turno de conversa anterior, serializável no estado do grafo."""

    role: Literal["user", "assistant"]
    content: str


class ChatRAGState(TypedDict, total=False):
    """Estado passado entre nós."""

    query: str
    patient_id: str
    chat_history: list[ChatHistoryTurnState]
    retrieved_docs: list[Document]
    sources: list[str]
    reasoning_steps: list[str]
    answer: str
