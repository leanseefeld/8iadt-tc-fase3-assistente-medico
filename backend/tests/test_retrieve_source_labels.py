"""Rótulos de fonte alinhados aos índices [n] do prompt de geração."""

from langchain_core.documents import Document

from assistente_medico_api.graph.nodes.retrieve import (
    format_context_block,
    format_source_label,
)


def test_format_source_label_uses_same_index_as_context_block() -> None:
    docs = [
        Document(
            page_content="chunk a",
            metadata={"source_stem": "artrite", "page_start": 1, "page_end": 2},
        ),
        Document(
            page_content="chunk b",
            metadata={"source_stem": "sepse", "page_start": 10, "page_end": 11},
        ),
    ]

    assert format_source_label(docs[0], 1) == "[1] PCDT artrite (pp. 1-2)"
    assert format_source_label(docs[1], 2) == "[2] PCDT sepse (pp. 10-11)"

    context = format_context_block(docs)
    assert context.startswith("[Documento 1]")
    assert "---" in context
    assert "[Documento 2]" in context
