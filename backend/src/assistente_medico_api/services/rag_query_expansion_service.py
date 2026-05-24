"""Serviços de reescrita e expansão estruturada da consulta RAG."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.nodes.generate import _build_llm
from assistente_medico_api.graph.rag_enhancement import expand_query_with_conitec_catalog

try:
    from assistente_medico_api.graph.rag_enhancement import load_local_conitec_catalog
except Exception:  # pragma: no cover - fallback para ambientes sem ingestão.
    load_local_conitec_catalog = None  # type: ignore[assignment]


_REWRITE_SYSTEM = """\
Você reformula a última pergunta do médico como uma única consulta autocontida para busca \
por similaridade em documentos dos Protocolos Clínicos e Diretrizes Terapêuticas (PCDT) do Brasil.
Preserve termos clínicos e CID/procedimentos quando citados no histórico.
Responda apenas com a consulta reformulada, sem prefixos nem explicações.\
"""


@dataclass(frozen=True)
class RetrievalQueryResolution:
    retrieval_query: str
    reasoning_steps: list[str]
    used_history: bool
    llm_used: bool
    error: str | None = None


@dataclass(frozen=True)
class QueryExpansionResult:
    expanded_query: str
    clinical_understanding: dict[str, Any]
    structured_terms: dict[str, Any]
    matched_cid10_codes: list[str]
    matched_diseases: list[str]
    matched_medications: list[str]
    query_expansion: dict[str, Any]


def _history_transcript(state: dict[str, Any]) -> str:
    lines: list[str] = []
    for turn in state.get("chat_history") or []:
        text = (turn.get("content") or "").strip()
        if not text:
            continue
        role = turn.get("role")
        if role == "user":
            lines.append(f"Médico: {text}")
        elif role == "assistant":
            lines.append(f"Assistente: {text}")
    return "\n".join(lines)


async def resolve_retrieval_query(
    *,
    state: dict[str, Any],
    query: str,
    settings: Settings,
) -> RetrievalQueryResolution:
    """Resolve a consulta de busca preservando o comportamento da main."""
    steps = list(state.get("reasoning_steps") or [])

    if not query:
        steps.append("Reescrita: pergunta vazia — sem consulta de busca.")
        return RetrievalQueryResolution(
            retrieval_query="",
            reasoning_steps=steps,
            used_history=False,
            llm_used=False,
        )

    transcript = _history_transcript(state)
    if not transcript:
        steps.append("Busca: sem histórico — usada pergunta literal na recuperação.")
        return RetrievalQueryResolution(
            retrieval_query=query,
            reasoning_steps=steps,
            used_history=False,
            llm_used=False,
        )

    llm = _build_llm(settings)
    human = (
        f"Histórico da conversa:\n{transcript}\n\n"
        f"Última pergunta do médico:\n{query}\n\n"
        "Reformule em uma consulta única para busca nos PCDTs."
    )
    try:
        result = await llm.ainvoke(
            [SystemMessage(content=_REWRITE_SYSTEM), HumanMessage(content=human)]
        )
        raw = (getattr(result, "content", None) or "").strip()
        if isinstance(raw, list):
            raw = "".join(str(part) for part in raw)
        retrieval_query = str(raw).strip() or query
        if retrieval_query == query:
            steps.append("Busca: falha na reescrita — usada pergunta literal na recuperação.")
            return RetrievalQueryResolution(
                retrieval_query=query,
                reasoning_steps=steps,
                used_history=True,
                llm_used=True,
                error="resposta vazia do modelo",
            )
        steps.append("Busca: pergunta reescrita com o histórico para recuperação.")
        return RetrievalQueryResolution(
            retrieval_query=retrieval_query,
            reasoning_steps=steps,
            used_history=True,
            llm_used=True,
        )
    except Exception as exc:
        steps.append("Busca: falha na reescrita — usada pergunta literal na recuperação.")
        return RetrievalQueryResolution(
            retrieval_query=query,
            reasoning_steps=steps,
            used_history=True,
            llm_used=True,
            error=str(exc)[:240],
        )


def _load_catalog() -> dict[str, Any] | None:
    if load_local_conitec_catalog is None:
        return None
    try:
        return load_local_conitec_catalog()
    except Exception:
        return None


def expand_query_for_retrieval(
    *,
    query: str,
    retrieval_query: str,
    settings: Settings,
) -> QueryExpansionResult:
    """Aplica a expansão estruturada preservando o refinamento da branch atual."""
    base_query = (retrieval_query or query or "").strip()
    catalog = _load_catalog()
    if not base_query or not catalog:
        expansion = expand_query_with_conitec_catalog(base_query, catalog or {}, max_terms=10)
        return QueryExpansionResult(
            expanded_query=expansion.get("expanded_query") or base_query,
            clinical_understanding=expansion.get("clinical_understanding") or {},
            structured_terms=expansion.get("structured_terms") or {},
            matched_cid10_codes=list(expansion.get("matched_cid10_codes") or []),
            matched_diseases=list(expansion.get("matched_diseases") or []),
            matched_medications=list(expansion.get("matched_medications") or []),
            query_expansion=expansion,
        )

    expansion = expand_query_with_conitec_catalog(base_query, catalog, max_terms=10)
    return QueryExpansionResult(
        expanded_query=expansion.get("expanded_query") or base_query,
        clinical_understanding=expansion.get("clinical_understanding") or {},
        structured_terms=expansion.get("structured_terms") or {},
        matched_cid10_codes=list(expansion.get("matched_cid10_codes") or []),
        matched_diseases=list(expansion.get("matched_diseases") or []),
        matched_medications=list(expansion.get("matched_medications") or []),
        query_expansion=expansion,
    )
