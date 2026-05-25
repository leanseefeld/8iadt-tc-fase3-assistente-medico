"""Neutral context formatting helpers shared by retrieve/generate/guardrail."""

from __future__ import annotations

from langchain_core.documents import Document

from assistente_medico_api.graph.rag_enhancement import format_context_document, format_rich_context_block


def format_context_block(docs: list[Document]) -> str:
    """Build the PCDT context block used in prompts."""
    return format_rich_context_block(docs)


def format_context_preview(docs: list[Document], *, max_docs: int = 2, max_chars: int = 1200) -> str:
    preview = "\n\n---\n\n".join(format_context_document(doc, i) for i, doc in enumerate(docs[:max_docs], start=1))
    return preview[:max_chars]
