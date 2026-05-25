"""Serviços de reescrita e expansão estruturada da consulta RAG."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.llm_client import AuxLlmTraceEntry, build_llm, tracked_ainvoke
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


def _rewrite_human_message(*, query: str, transcript: str) -> str:
    """Monta o prompt de reescrita; primeiro turno omite bloco de histórico."""
    if transcript:
        return (
            f"Histórico da conversa:\n{transcript}\n\n"
            f"Última pergunta do médico:\n{query}\n\n"
            "Reformule em uma consulta única para busca nos PCDTs."
        )
    return (
        f"Pergunta do médico:\n{query}\n\n"
        "Reformule em uma consulta única e autocontida para busca nos PCDTs."
    )


async def resolve_retrieval_query(
    *,
    state: dict[str, Any],
    query: str,
    settings: Settings,
    trace: list[AuxLlmTraceEntry] | None = None,
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
    used_history = bool(transcript)
    llm = build_llm(settings)
    human = _rewrite_human_message(query=query, transcript=transcript)
    rewrite_messages = [
        SystemMessage(content=_REWRITE_SYSTEM),
        HumanMessage(content=human),
    ]
    active_trace = trace if trace is not None else []
    try:
        result = await tracked_ainvoke(
            llm,
            rewrite_messages,
            call_type="rewrite",
            trace=active_trace,
            settings=settings,
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
                used_history=used_history,
                llm_used=True,
                error="resposta vazia ou igual à pergunta",
            )
        if used_history:
            steps.append("Busca: pergunta reescrita com o histórico para recuperação.")
        else:
            steps.append("Busca: pergunta reescrita para recuperação.")
        return RetrievalQueryResolution(
            retrieval_query=retrieval_query,
            reasoning_steps=steps,
            used_history=used_history,
            llm_used=True,
        )
    except Exception as exc:
        steps.append("Busca: falha na reescrita — usada pergunta literal na recuperação.")
        return RetrievalQueryResolution(
            retrieval_query=query,
            reasoning_steps=steps,
            used_history=used_history,
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


def _has_disease(expansion: dict) -> bool:
    st = expansion.get("structured_terms") or {}
    return bool(st.get("disease") or st.get("diretriz"))


def expand_query_for_retrieval(
    *,
    query: str,
    retrieval_query: str,
) -> QueryExpansionResult:
    """Aplica a expansão estruturada preservando o refinamento da branch atual.

    Estratégia: expande a query ORIGINAL primeiro, pois abreviações curtas (sgb, les, ar)
    matcham melhor no catálogo do que a versão reescrita pelo LLM, que tende a produzir
    frases genéricas do tipo "conforme especificado no PCDT do Brasil" que diluem o match.
    Só usa a query reescrita se a original não tiver detectado doença e a reescrita tiver.
    """
    original_query = (query or "").strip()
    base_query = (retrieval_query or original_query).strip()
    catalog = _load_catalog()

    # Sempre expande a query original para detecção de doença/CID
    orig_expansion = expand_query_with_conitec_catalog(original_query or base_query, catalog or {}, max_terms=10)

    if original_query == base_query or _has_disease(orig_expansion):
        # Query original já tem doença detectada — usa diretamente
        expansion = orig_expansion
    else:
        # Original não detectou doença; tenta a reescrita (útil em follow-ups como "e os critérios de exclusão?")
        base_expansion = expand_query_with_conitec_catalog(base_query, catalog or {}, max_terms=10)
        expansion = base_expansion if _has_disease(base_expansion) else orig_expansion

    return QueryExpansionResult(
        expanded_query=expansion.get("expanded_query") or base_query,
        clinical_understanding=expansion.get("clinical_understanding") or {},
        structured_terms=expansion.get("structured_terms") or {},
        query_expansion=expansion,
    )
