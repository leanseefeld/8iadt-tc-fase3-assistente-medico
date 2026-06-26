"""Nós do subgrafo de busca especializada (N queries via CoT + fusão RRF).

Caminho isolado e independente do RAG legado: sem catálogo Conitec, sem
``structured_terms`` e sem expansão estruturada de query. O médico pergunta,
o LLM planeja até N consultas, cada uma busca no Chroma e os resultados são
fundidos por Reciprocal Rank Fusion (RRF).
"""

from __future__ import annotations

import json
import logging
import time

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.llm_client import AuxLlmTraceEntry, build_llm, tracked_ainvoke
from assistente_medico_api.graph.state import ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate

_log = logging.getLogger("assistente_medico.rag.search")

_PLAN_SYSTEM = """\
Você gera consultas de busca para recuperar trechos de Protocolos Clínicos e
Diretrizes Terapêuticas (PCDT) brasileiros de uma base vetorial (Chroma).

COMO A BUSCA FUNCIONA
A base compara a suas queries com fragmentos de texto dos protocolos por similaridade
semântica. Isso significa que cada query deve parecer um *trecho do próprio protocolo*,
não uma pergunta. O protocolo nunca diz "qual o tratamento?"; ele diz coisas como
"esquema terapêutico: metformina 500 mg via oral". Escreva como ele escreve.

SEÇÕES DISPONÍVEIS NOS PCDTs
Use esses nomes de seção como prefixo quando a faceta for relevante:
Critérios de diagnóstico | Critérios de inclusão | Critérios de exclusão |
Esquema terapêutico | Posologia e modo de uso | Monitoramento |
Contraindicações | Efeitos adversos | Benefícios esperados

REGRAS PARA CADA QUERY
1. Tamanho: 4 a 8 termos clínicos. Omita artigos, preposições e verbos genéricos.
2. Identifiers: inclua o nome técnico completo da doença ou medicamento + sigla
(DM2, HIV, TEP…) + CID-10 quando souber. Podem estar na mesma query ou em queries
separadas cobrindo o mesmo identifier de ângulos diferentes.
3. Autossuficiente: inclua sempre o nome da condição/medicamento, mesmo que já
apareça em outra query ou no histórico. A busca não tem memória entre queries.
4. Facetas distintas: cada query cobre uma faceta diferente (diagnóstico, tratamento,
posologia, monitoramento, contraindicações…). Evite variações da mesma faceta.
5. Ordenação: coloque primeiro a query mais provável de ter conteúdo direto no
protocolo; as menos prováveis por último.

Raciocine sobre as facetas relevantes da pergunta.
Pense em respostas prováveis da pergunta.
Pense nas regras explicadas e então gere as queries.

Responda APENAS com JSON puro, sem markdown:
{"reasoning":"<raciocínio>","queries":["<query 1>","<query 2>"]}
Gere no máximo %(max)d queries; gere menos quando a pergunta for simples.
"""


def _history_transcript(state: ChatRAGState) -> str:
    """Transcreve o histórico para dar contexto a perguntas de acompanhamento."""
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


def _parse_queries(raw: str, *, max_n: int, fallback: str) -> list[str]:
    """Extrai a lista de consultas do JSON do LLM; em falha, usa a pergunta literal."""
    text = (raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            raw_queries = data.get("queries") if isinstance(data, dict) else None
            queries: list[str] = []
            seen: set[str] = set()
            for item in raw_queries or []:
                q = str(item).strip()
                key = q.lower()
                if q and key not in seen:
                    seen.add(key)
                    queries.append(q)
            if queries:
                return queries[:max_n]
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    return [fallback] if fallback else []


def _extract_reasoning(raw: str) -> str:
    """Extrai o campo 'reasoning' do JSON do LLM; retorna '' se ausente ou inválido."""
    text = (raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return str(data.get("reasoning") or "") if isinstance(data, dict) else ""
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    return ""


async def plan_queries_node(state: ChatRAGState, settings: Settings) -> dict:
    """Gera até N consultas de busca com chain-of-thought (nó intermediário com LLM)."""
    query = (state.get("query") or "").strip()
    steps = list(state.get("reasoning_steps") or [])
    trace: list[AuxLlmTraceEntry] = list(state.get("aux_llm_trace") or [])
    max_n = max(1, int(getattr(settings, "rag_multi_query_max", 4)))
    t0 = time.perf_counter()

    if not query:
        steps.append("Busca: pergunta vazia — sem consultas geradas.")
        return {"search_queries": [], "reasoning_steps": steps, "aux_llm_trace": trace}

    transcript = _history_transcript(state)
    human = (
        f"Histórico da conversa:\n{transcript}\n\nÚltima pergunta do médico:\n{query}"
        if transcript else query
    )
    error: str | None = None
    try:
        llm = build_llm(
            settings,
            min_p=getattr(settings, "rag_multi_query_min_p", None),
            max_tokens=getattr(settings, "rag_multi_query_max_tokens", None),
        )
        result = await tracked_ainvoke(
            llm,
            [SystemMessage(content=_PLAN_SYSTEM % {"max": max_n}), HumanMessage(content=human)],
            call_type="multi_query",
            trace=trace,
            settings=settings,
        )
        raw = getattr(result, "content", None) or ""
        if isinstance(raw, list):
            raw = "".join(str(part) for part in raw)
        raw_str = str(raw)
        queries = _parse_queries(raw_str, max_n=max_n, fallback=query)
        llm_reasoning = _extract_reasoning(raw_str)
    except Exception as exc:  # noqa: BLE001 - qualquer falha cai no fallback de 1 query.
        error = str(exc)[:240]
        llm_reasoning = ""
        raw_str = ""
        _log.exception("plan_queries_node: LLM call failed (model=%s provider=%s)",
                       getattr(settings, "llm_chat_model", "?"),
                       getattr(settings, "llm_chat_provider", "?"))
        queries = [query]

    if error or queries == [query]:
        steps.append("Busca: fallback para a pergunta literal (planejamento indisponível).")
    else:
        steps.append(f"Busca: {len(queries)} consulta(s) planejada(s) — " + " | ".join(queries))

    audit(
        "rag_multi_query_plan_done",
        kind="rag",
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        patient_id=state.get("patient_id") or None,
        query_snippet=truncate(query),
        num_queries=len(queries),
        error=error,
    )

    return {
        "search_queries": queries,
        "multi_query_debug": {"queries": queries, "reasoning": llm_reasoning, "raw": raw_str, "error": error},
        "reasoning_steps": steps,
        "aux_llm_trace": trace,
    }


def _doc_key(doc: Document) -> str:
    """Chave estável para dedup: id do documento ou stem+página como fallback."""
    if getattr(doc, "id", None):
        return str(doc.id)
    meta = doc.metadata or {}
    return f"{meta.get('source_stem', '?')}:{meta.get('chunk_index', meta.get('page_start', '?'))}"


def _rrf_fuse(
    results_per_query: list[list[tuple[Document, float]]],
    *,
    rrf_k: int,
    top_k: int,
) -> list[Document]:
    """Funde rankings de várias buscas por Reciprocal Rank Fusion e deduplica."""
    scores: dict[str, float] = {}
    best_doc: dict[str, Document] = {}
    hits: dict[str, int] = {}
    for pairs in results_per_query:
        for rank, (doc, _dense_score) in enumerate(pairs, start=1):
            key = _doc_key(doc)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            hits[key] = hits.get(key, 0) + 1
            if key not in best_doc:
                best_doc[key] = doc
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    fused: list[Document] = []
    for key, score in ordered[:top_k]:
        doc = best_doc[key]
        meta = dict(doc.metadata or {})
        meta["rrf_score"] = round(score, 6)
        meta["matched_queries"] = hits[key]
        fused.append(Document(page_content=doc.page_content, metadata=meta, id=getattr(doc, "id", None)))
    return fused


def _format_source_label(doc: Document, index: int) -> str:
    """Rótulo de fonte local (independente do RAG legado)."""
    meta = doc.metadata or {}
    diretriz = meta.get("diretriz") or meta.get("disease") or meta.get("source_stem", "?")
    section = meta.get("section")
    p0 = meta.get("page_start", "?")
    p1 = meta.get("page_end", "?")
    body = f"PCDT {diretriz} - {section} (pp. {p0}-{p1})" if section else f"PCDT {diretriz} (pp. {p0}-{p1})"
    return f"[{index}] {body}"


def search_node(state: ChatRAGState, *, store: Chroma, settings: Settings) -> dict:
    """Executa cada consulta no Chroma e funde por RRF (nó síncrono de I/O)."""
    t0 = time.perf_counter()
    queries = [q for q in (state.get("search_queries") or []) if q.strip()]
    if not queries:
        queries = [q for q in [(state.get("query") or "").strip()] if q]

    per_query_k = max(1, int(getattr(settings, "rag_retrieve_candidates_k", 30)))
    final_k = max(1, int(getattr(settings, "rag_retrieve_final_k", 6)))
    rrf_k = max(1, int(getattr(settings, "rag_multi_query_rrf_k", 60)))

    results_per_query: list[list[tuple[Document, float]]] = []
    per_query_counts: list[int] = []
    for q in queries:
        try:
            pairs = store.similarity_search_with_score(q, k=per_query_k)
        except Exception:  # noqa: BLE001 - uma consulta com erro não derruba a busca.
            pairs = []
        results_per_query.append([(doc, float(score)) for doc, score in pairs])
        per_query_counts.append(len(pairs))

    fused = _rrf_fuse(results_per_query, rrf_k=rrf_k, top_k=final_k)
    sources = [_format_source_label(doc, i) for i, doc in enumerate(fused, start=1)]

    steps = list(state.get("reasoning_steps") or [])
    steps.append(
        f"Busca: {len(queries)} consulta(s), {sum(per_query_counts)} candidato(s) brutos → "
        f"{len(fused)} trecho(s) após fusão RRF."
    )

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    audit(
        "rag_multi_query_search_done",
        kind="rag",
        latency_ms=latency_ms,
        patient_id=state.get("patient_id") or None,
        num_queries=len(queries),
        per_query_counts=per_query_counts,
        fused_count=len(fused),
        fusion="rrf",
    )

    return {
        "retrieved_docs": fused,
        "candidate_docs": fused,
        "sources": sources,
        "generation_mode": "grounded_answer" if fused else "insufficient_context",
        "context_sufficient": bool(fused),
        "insufficiency_reason": None if fused else "Nenhum trecho recuperado na busca.",
        "reasoning_steps": steps,
    }
