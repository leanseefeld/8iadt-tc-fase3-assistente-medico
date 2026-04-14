"""Estado do grafo de chat RAG."""

from __future__ import annotations

from typing import TypedDict

from langchain_core.documents import Document


class ChatRAGState(TypedDict, total=False):
    """Estado passado entre nós."""

    query: str
    patient_id: str
    retrieved_docs: list[Document]
    sources: list[str]
    reasoning_steps: list[str]
    answer: str
