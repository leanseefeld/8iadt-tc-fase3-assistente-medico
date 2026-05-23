#!/usr/bin/env python3
"""
RAG Inspector (standalone).

Objetivo: inspecionar embeddings, retrieve (Chroma), montagem de contexto/prompt e geração (Ollama)
sem iniciar a API/frontend.

Como rodar (venv ativo):
    cd llm && streamlit run scripts/rag_inspector_app.py

Observação: ``llm/.streamlit/config.toml`` desativa o file watcher do Streamlit
para evitar imports lazy ruidosos de bibliotecas como ``transformers``.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any, cast

import asyncio
import builtins
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
for src_path in (REPO_ROOT / "backend" / "src", REPO_ROOT / "llm" / "src"):
    src = str(src_path)
    if src not in sys.path:
        sys.path.insert(0, src)

IMPORT_ERROR: ModuleNotFoundError | None = None
try:
    from langchain_core.documents import Document
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from assistente_medico_api.config import Settings, resolve_chroma_persist_dir
    from assistente_medico_api.graph.nodes.generate import _build_messages, generate_node
    from assistente_medico_api.graph.nodes.guardrail import guardrail_node
    from assistente_medico_api.graph.nodes.retrieve import (
        format_context_block,
        format_source_label,
        retrieve_node,
    )
    from assistente_medico_api.graph.nodes.rewrite import rewrite_query_node
    from pcdt_ingest.embed import (
        CHROMA_COLLECTION_PCDT,
        build_ollama_embeddings,
        ollama_single_embed_with_token_count,
        open_chroma_vectorstore,
    )
    from pcdt_ingest.paths import vectorstore_chroma_dir
except ModuleNotFoundError as exc:
    IMPORT_ERROR = exc
    Document = Any  # type: ignore[assignment]
    AIMessage = Any  # type: ignore[assignment]
    HumanMessage = Any  # type: ignore[assignment]
    SystemMessage = Any  # type: ignore[assignment]
    CHROMA_COLLECTION_PCDT = "pcdt"

    def resolve_chroma_persist_dir(settings: Any) -> Path:  # type: ignore[no-redef]
        path = getattr(settings, "chroma_persist_dir", None)
        return Path(path) if path else vectorstore_chroma_dir()

    def _build_messages(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError("Dependências do RAG Inspector não instaladas.")

    async def generate_node(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError("Dependências do RAG Inspector não instaladas.")

    async def guardrail_node(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError("Dependências do RAG Inspector não instaladas.")

    def format_context_block(docs: list[Any]) -> str:  # type: ignore[no-redef]
        return ""

    def format_source_label(doc: Any) -> str:  # type: ignore[no-redef]
        return "PCDT ? (pp. ?-?)"

    def retrieve_node(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError("Dependências do RAG Inspector não instaladas.")

    async def rewrite_query_node(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError("Dependências do RAG Inspector não instaladas.")

    def vectorstore_chroma_dir() -> Path:
        return Path.cwd().parent / "vectorstore" / "chroma"

    def build_ollama_embeddings(*, model: str, base_url: str):  # type: ignore[no-redef]
        raise RuntimeError("Dependências do RAG Inspector não instaladas.")

    def ollama_single_embed_with_token_count(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError("Dependências do RAG Inspector não instaladas.")

    def open_chroma_vectorstore(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError("Dependências do RAG Inspector não instaladas.")


@dataclass(frozen=True)
class InspectorSettings:
    ollama_base_url: str
    ollama_embed_model: str
    ollama_chat_model: str
    chroma_persist_dir: str
    chroma_collection: str
    retrieval_k: int
    rag_retrieve_candidates_k: int
    rag_retrieve_final_k: int
    rag_require_catalog_match_when_confident: bool
    rag_min_final_score_with_catalog: float
    rag_audit_enabled: bool
    rag_audit_jsonl: str
    llm_stream_timeout_s: float


@dataclass(frozen=True)
class Timing:
    store_ms: float | None
    rewrite_ms: float | None
    embed_ms: float | None
    retrieve_ms: float | None
    assemble_ms: float | None
    generate_ms: float | None
    guardrail_ms: float | None
    total_ms: float | None


def _default_settings() -> InspectorSettings:
    backend_env = REPO_ROOT / "backend" / ".env"
    backend_cfg = Settings(_env_file=backend_env if backend_env.exists() else None)
    chroma_dir = resolve_chroma_persist_dir(backend_cfg)
    return InspectorSettings(
        ollama_base_url=backend_cfg.ollama_base_url,
        ollama_embed_model=backend_cfg.ollama_embed_model,
        ollama_chat_model=backend_cfg.ollama_chat_model,
        chroma_persist_dir=str(chroma_dir),
        chroma_collection=backend_cfg.chroma_collection,
        retrieval_k=backend_cfg.retrieval_k,
        rag_retrieve_candidates_k=backend_cfg.rag_retrieve_candidates_k,
        rag_retrieve_final_k=backend_cfg.rag_retrieve_final_k,
        rag_require_catalog_match_when_confident=backend_cfg.rag_require_catalog_match_when_confident,
        rag_min_final_score_with_catalog=backend_cfg.rag_min_final_score_with_catalog,
        rag_audit_enabled=backend_cfg.rag_audit_enabled,
        rag_audit_jsonl=str(backend_cfg.rag_audit_jsonl),
        llm_stream_timeout_s=backend_cfg.llm_stream_timeout_s,
    )


def _vec_stats(vec: list[float]) -> dict[str, float]:
    if not vec:
        return {"dim": 0.0, "l2": 0.0, "l1": 0.0, "mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    dim = float(len(vec))
    l2 = math.sqrt(sum(v * v for v in vec))
    l1 = sum(abs(v) for v in vec)
    mean = sum(vec) / len(vec)
    var = sum((v - mean) ** 2 for v in vec) / max(1, (len(vec) - 1))
    std = math.sqrt(var)
    return {
        "dim": dim,
        "l2": float(l2),
        "l1": float(l1),
        "mean": float(mean),
        "std": float(std),
        "min": float(min(vec)),
        "max": float(max(vec)),
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _format_exception(exc: BaseException) -> str:
    """Mensagem compacta preservando tipo quando ``str(exc)`` vem vazio."""
    exc_type = f"{type(exc).__module__}.{type(exc).__name__}"
    message = str(exc).strip() or repr(exc)
    if isinstance(exc, TimeoutError | builtins.TimeoutError | asyncio.TimeoutError) or "Timeout" in type(exc).__name__:
        return (
            f"{exc_type}: {message}. "
            "Possível timeout de geração; aumente `Timeout geração (s)`, reduza `k`/contexto "
            "ou use um modelo mais rápido."
        )
    return f"{exc_type}: {message}"


def _backend_settings(cfg: InspectorSettings) -> Settings:
    return Settings(
        ollama_base_url=cfg.ollama_base_url,
        ollama_embed_model=cfg.ollama_embed_model,
        ollama_chat_model=cfg.ollama_chat_model,
        chroma_persist_dir=Path(cfg.chroma_persist_dir),
        chroma_collection=cfg.chroma_collection,
        retrieval_k=int(cfg.retrieval_k),
        rag_retrieve_candidates_k=int(cfg.rag_retrieve_candidates_k),
        rag_retrieve_final_k=int(cfg.rag_retrieve_final_k),
        rag_require_catalog_match_when_confident=bool(cfg.rag_require_catalog_match_when_confident),
        rag_min_final_score_with_catalog=float(cfg.rag_min_final_score_with_catalog),
        rag_audit_enabled=bool(cfg.rag_audit_enabled),
        rag_audit_jsonl=Path(cfg.rag_audit_jsonl),
        llm_stream_timeout_s=float(cfg.llm_stream_timeout_s),
    )


def _load_store(cfg: InspectorSettings):
    embeddings = build_ollama_embeddings(model=cfg.ollama_embed_model, base_url=cfg.ollama_base_url)
    settings = _backend_settings(cfg)
    return open_chroma_vectorstore(
        persist_directory=resolve_chroma_persist_dir(settings),
        embedding_function=embeddings,
        collection_name=cfg.chroma_collection,
    )


class InspectableStore:
    """Wrapper para capturar os scores sem alterar o retrieve_node do backend."""

    def __init__(self, store: Any) -> None:
        self._store = store
        self.last_pairs: list[tuple[Document, float]] = []

    def similarity_search_with_score(self, query: str, k: int = 6):
        pairs = self._store.similarity_search_with_score(query, k=k)
        self.last_pairs = list(pairs)
        return pairs


def _message_to_payload(message: Any) -> dict[str, str]:
    if isinstance(message, SystemMessage):
        role = "system"
    elif isinstance(message, HumanMessage):
        role = "user"
    elif isinstance(message, AIMessage):
        role = "assistant"
    else:
        role = "message"
    return {"role": role, "content": str(getattr(message, "content", str(message)))}


def _run_async(coro):
    return asyncio.run(coro)


def _fmt_ms(value: Any) -> str:
    return f"{float(value):.1f}" if value is not None else "-"


def _score_summary(scores: list[float]) -> dict[str, float] | None:
    if not scores:
        return None
    return {
        "best": min(scores),
        "worst": max(scores),
        "spread": max(scores) - min(scores),
        "mean": sum(scores) / len(scores),
    }


def _doc_payload(doc: Document, rank: int) -> dict[str, Any]:
    meta = dict(doc.metadata or {})
    return {
        "rank": rank,
        "source_label": format_source_label(doc),
        "doc_id": getattr(doc, "id", None),
        "metadata": meta,
        "dense_score": meta.get("dense_score"),
        "dense_rank": meta.get("dense_rank"),
        "dense_rank_score": meta.get("dense_rank_score"),
        "heuristic_score": meta.get("heuristic_score"),
        "final_score": meta.get("final_score"),
        "ranking_reasons": meta.get("ranking_reasons") or [],
        "content_preview": (doc.page_content or "").strip()[:500],
        "content": (doc.page_content or "").strip(),
    }


def _candidate_payload(doc: Document, score: float, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "dense_score": float(score),
        "source_label": format_source_label(doc),
        "doc_id": getattr(doc, "id", None),
        "metadata": dict(doc.metadata or {}),
        "content_preview": (doc.page_content or "").strip()[:500],
        "content": (doc.page_content or "").strip(),
    }


def _render_educational_tips(*, query: str, has_docs: bool, scores: list[float]) -> None:
    st.subheader("Modo educacional (dicas)")
    tips: list[str] = []
    if not query.strip():
        tips.append("Comece com uma pergunta curta e objetiva (uma intenção por vez).")
    if not has_docs:
        tips.append("Sem resultados: confirme o `persist_dir`, `collection` e se o `build-vectorstore` já rodou.")
        tips.append("Confirme se o modelo de embedding do retrieve é o mesmo da ingestão (`nomic-embed-text` por padrão).")
    if has_docs and scores:
        tips.append("Compare os scores entre execuções apenas dentro do mesmo setup (modelo/coleção).")
        tips.append("Se os top chunks parecem “perto, mas não exatamente”, teste aumentar `k` e melhorar chunking (títulos/seções).")
    tips.append("Uma melhoria comum é adicionar uma etapa de *query rewriting* antes do retrieve (sinônimos médicos, CID, termos do PCDT).")
    tips.append("Outra melhoria comum é hibridizar (BM25 + denso) para normas longas; hoje você está só no denso (Chroma).")
    for t in tips:
        st.markdown(f"- {t}")


def main() -> None:
    st.set_page_config(page_title="RAG Inspector", layout="wide")
    st.title("RAG Inspector (PCDT) — debug completo do pipeline")

    if IMPORT_ERROR is not None:
        st.error(f"Dependência ausente: `{IMPORT_ERROR.name}`")
        st.markdown(
            "\n".join(
                [
                    "Para usar o Inspector, instale as dependências do pacote `llm` no mesmo Python do Streamlit:",
                    "",
                    "```bash",
                    "cd llm",
                    "pip install -e .",
                    "streamlit run scripts/rag_inspector_app.py",
                    "```",
                ]
            )
        )
        st.info(
            "Se usar múltiplos Pythons (pyenv/venv), rode `python -m pip install -e .` "
            "com o mesmo `python` que executa o `streamlit`."
        )
        st.stop()

    if "last_run" not in st.session_state:
        st.session_state["last_run"] = None

    cfg0 = _default_settings()
    with st.sidebar:
        st.header("Configuração")
        cfg = InspectorSettings(
            ollama_base_url=st.text_input("Ollama base URL", value=cfg0.ollama_base_url),
            ollama_embed_model=st.text_input("Modelo de embedding", value=cfg0.ollama_embed_model),
            ollama_chat_model=st.text_input(
                "Modelo de chat",
                value="llama3.2:3b",
                help=(
                    "Padrão do painel para caber em máquinas com menos memória. "
                    f"Modelo configurado no backend: {cfg0.ollama_chat_model}."
                ),
            ),
            chroma_persist_dir=st.text_input("Chroma persist dir", value=cfg0.chroma_persist_dir),
            chroma_collection=st.text_input("Chroma collection", value=cfg0.chroma_collection),
            retrieval_k=st.number_input(
                "k legado (retrieval_k)",
                min_value=1,
                max_value=50,
                value=int(cfg0.retrieval_k),
                step=1,
                help="Mantido por compatibilidade; o backend atual usa k inicial e k final abaixo.",
            ),
            rag_retrieve_candidates_k=st.number_input(
                "k inicial RAG (candidatos)",
                min_value=1,
                max_value=100,
                value=int(cfg0.rag_retrieve_candidates_k),
                step=1,
            ),
            rag_retrieve_final_k=st.number_input(
                "k final RAG (rerank)",
                min_value=1,
                max_value=50,
                value=int(cfg0.rag_retrieve_final_k),
                step=1,
            ),
            rag_require_catalog_match_when_confident=st.checkbox(
                "Exigir match de catálogo quando confiante",
                value=bool(cfg0.rag_require_catalog_match_when_confident),
            ),
            rag_min_final_score_with_catalog=st.number_input(
                "Score mínimo com catálogo",
                min_value=-10.0,
                max_value=20.0,
                value=float(cfg0.rag_min_final_score_with_catalog),
                step=0.5,
            ),
            rag_audit_enabled=st.checkbox("Registrar auditoria RAG", value=bool(cfg0.rag_audit_enabled)),
            rag_audit_jsonl=st.text_input("Arquivo auditoria RAG", value=cfg0.rag_audit_jsonl),
            llm_stream_timeout_s=st.number_input("Timeout LLM (s)", min_value=5.0, max_value=600.0, value=float(cfg0.llm_stream_timeout_s), step=5.0),
        )
        st.caption(
            "Dica: o path default do Chroma é `vectorstore/chroma` na raiz do repositório. "
            "Os defaults vêm da mesma classe Settings usada pela API."
        )

    tab_run, tab_vectorstore, tab_export = st.tabs(["Executar & inspecionar", "Vectorstore", "Exportar JSON"])

    with tab_run:
        col_l, col_r = st.columns([1.15, 0.85], gap="large")

        with col_l:
            st.subheader("Entrada")
            query = st.text_area(
                "Texto do médico (query)",
                height=140,
                value="Quais são os critérios de inclusão para sgb?",
            )
            history_raw = st.text_area(
                "Histórico JSON opcional",
                height=110,
                value="[]",
                help='Mesmo formato do backend: [{"role":"user","content":"..."},{"role":"assistant","content":"..."}]',
            )
            run_mode = st.radio(
                "Modo de execução",
                options=["RAG apenas", "RAG + geração LLM", "Fluxo completo (geração + guardrail)"],
                index=2,
                horizontal=True,
            )
            rag_focus_mode = run_mode == "RAG apenas"
            run_generate = not rag_focus_mode
            run_guardrail = run_mode == "Fluxo completo (geração + guardrail)"
            educational_mode = st.checkbox("Modo educacional", value=True)
            debug_embed = st.checkbox("Analisar embedding (vetor + stats)", value=True)
            run_btn = st.button("Rodar pipeline", type="primary")

        with col_r:
            st.subheader("Flow diagram (atual)")
            flow_text = "backend.rewrite  →  backend.retrieve(expand + chroma + rerank)  →  backend.prompt_preview"
            if run_generate:
                flow_text = f"{flow_text}  →  backend.generate"
            if run_guardrail:
                flow_text = f"{flow_text}  →  backend.guardrail"
            st.code(flow_text, language="text")
            st.subheader("Performance (última execução)")
            last = st.session_state.get("last_run")
            if last and isinstance(last, dict):
                t = cast(dict[str, Any], last.get("timing") or {})
                metric_cols = st.columns(4)
                metric_cols[0].metric("total (ms)", _fmt_ms(t.get("total_ms")))
                metric_cols[1].metric("rewrite (ms)", _fmt_ms(t.get("rewrite_ms")))
                metric_cols[2].metric("retrieve (ms)", _fmt_ms(t.get("retrieve_ms")))
                metric_cols[3].metric("generate (ms)", _fmt_ms(t.get("generate_ms")))

                with st.expander("Tempos por etapa", expanded=False):
                    st.dataframe(
                        [
                            {"etapa": "abrir Chroma", "ms": t.get("store_ms")},
                            {"etapa": "embedding debug", "ms": t.get("embed_ms")},
                            {"etapa": "rewrite", "ms": t.get("rewrite_ms")},
                            {"etapa": "retrieve", "ms": t.get("retrieve_ms")},
                            {"etapa": "contexto + prompt", "ms": t.get("assemble_ms")},
                            {"etapa": "generate", "ms": t.get("generate_ms")},
                            {"etapa": "guardrail", "ms": t.get("guardrail_ms")},
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
            else:
                st.caption("Rode uma vez para ver métricas.")

        if run_btn:
            run_started = time.perf_counter()
            errors: list[str] = []
            timing = Timing(
                store_ms=None,
                rewrite_ms=None,
                embed_ms=None,
                retrieve_ms=None,
                assemble_ms=None,
                generate_ms=None,
                guardrail_ms=None,
                total_ms=None,
            )
            embed_info: dict[str, Any] | None = None
            raw_candidates: list[tuple[Document, float]] = []
            answer_text: str | None = None
            generation_model_used: str | None = None
            prompt_messages: list[dict[str, str]] | None = None
            context_text: str | None = None
            final_state: dict[str, Any] = {
                "query": query,
                "patient_id": "",
                "chat_history": [],
                "retrieved_docs": [],
                "sources": [],
                "reasoning_steps": [],
                "answer": "",
                "retrieval_query": "",
            }
            backend_settings = _backend_settings(cfg)

            try:
                parsed_history = json.loads(history_raw or "[]")
                if not isinstance(parsed_history, list):
                    raise ValueError("o histórico precisa ser uma lista")
                final_state["chat_history"] = [
                    {"role": str(t.get("role")), "content": str(t.get("content", "")).strip()}
                    for t in parsed_history
                    if isinstance(t, dict) and str(t.get("role")) in {"user", "assistant"} and str(t.get("content", "")).strip()
                ]
            except Exception as exc:
                errors.append(f"Histórico JSON inválido; executando sem histórico: {_format_exception(exc)}")

            # --- Load store ---
            try:
                t0 = time.perf_counter()
                store = _load_store(cfg)
                timing = replace(timing, store_ms=(time.perf_counter() - t0) * 1000.0)
            except Exception as exc:
                errors.append(f"Falha ao abrir Chroma: {_format_exception(exc)}")
                store = None

            # --- Embedding analysis (optional) ---
            if debug_embed and query.strip():
                try:
                    emb = build_ollama_embeddings(model=cfg.ollama_embed_model, base_url=cfg.ollama_base_url)
                    t0 = time.perf_counter()
                    vec, n_tok = ollama_single_embed_with_token_count(emb, query)
                    timing = replace(timing, embed_ms=(time.perf_counter() - t0) * 1000.0)
                    embed_info = {
                        "token_count": n_tok,
                        "stats": _vec_stats(vec),
                        "vector_head": vec[:32],
                        "vector_tail": vec[-8:] if len(vec) >= 8 else vec,
                    }
                except Exception as exc:
                    errors.append(f"Falha ao analisar embedding via Ollama: {_format_exception(exc)}")

            # --- Backend rewrite + retrieve ---
            if store is not None and query.strip():
                try:
                    t0 = time.perf_counter()
                    rewrite_out = cast(dict[str, Any], _run_async(rewrite_query_node(cast(Any, final_state), backend_settings)))
                    timing = replace(timing, rewrite_ms=(time.perf_counter() - t0) * 1000.0)
                    final_state.update(rewrite_out)

                    inspectable_store = InspectableStore(store)
                    t0 = time.perf_counter()
                    retrieve_out = retrieve_node(cast(Any, final_state), store=cast(Any, inspectable_store), settings=backend_settings)
                    timing = replace(timing, retrieve_ms=(time.perf_counter() - t0) * 1000.0)
                    final_state.update(retrieve_out)
                    raw_candidates = inspectable_store.last_pairs
                except Exception as exc:
                    errors.append(f"Falha no retrieve do backend: {_format_exception(exc)}")

            docs = cast(list[Document], final_state.get("retrieved_docs") or [d for d, _ in raw_candidates])

            # --- Backend context + prompt preview ---
            try:
                t0 = time.perf_counter()
                context_text = format_context_block(docs)
                messages = _build_messages(cast(Any, final_state))
                prompt_messages = [_message_to_payload(m) for m in messages]
                timing = replace(timing, assemble_ms=(time.perf_counter() - t0) * 1000.0)
            except Exception as exc:
                errors.append(f"Falha ao montar contexto/prompt: {_format_exception(exc)}")

            # --- Backend generate (optional) ---
            if run_generate and query.strip():
                try:
                    t0 = time.perf_counter()
                    with st.status("Gerando resposta (streaming)...", expanded=False):
                        generate_out = cast(dict[str, Any], _run_async(generate_node(cast(Any, final_state), backend_settings)))
                    final_state.update(generate_out)
                    answer_text = str(final_state.get("answer") or "")
                    generation_model_used = cfg.ollama_chat_model
                    timing = replace(timing, generate_ms=(time.perf_counter() - t0) * 1000.0)
                except Exception as exc:
                    errors.append(f"Falha na geração do backend com `{cfg.ollama_chat_model}`: {_format_exception(exc)}")

            if run_guardrail and answer_text:
                try:
                    t0 = time.perf_counter()
                    guardrail_out = cast(dict[str, Any], _run_async(guardrail_node(cast(Any, final_state), backend_settings)))
                    final_state.update(guardrail_out)
                    answer_text = str(final_state.get("answer") or "")
                    timing = replace(timing, guardrail_ms=(time.perf_counter() - t0) * 1000.0)
                except Exception as exc:
                    errors.append(f"Falha no guardrail do backend: {_format_exception(exc)}")

            timing = replace(timing, total_ms=(time.perf_counter() - run_started) * 1000.0)
            candidate_scores = [float(s) for _, s in raw_candidates]
            dense_score_summary = _score_summary(candidate_scores)
            final_scores = [
                float(doc.metadata["final_score"])
                for doc in docs
                if isinstance(doc.metadata, dict) and doc.metadata.get("final_score") is not None
            ]
            final_score_summary = _score_summary(final_scores)
            query_expansion = cast(dict[str, Any], final_state.get("query_expansion") or {})
            audit_payload = cast(dict[str, Any], final_state.get("rag_audit_payload") or {})
            structured_terms = cast(dict[str, Any], query_expansion.get("structured_terms") or {})
            catalog_filter = cast(dict[str, Any], audit_payload or query_expansion.get("_catalog_filter_info") or {})

            payload: dict[str, Any] = {
                "timestamp": _now_iso(),
                "settings": asdict(cfg),
                "input": {"query": query, "chat_history": final_state.get("chat_history") or []},
                "mode": {
                    "name": run_mode,
                    "rag_focus_mode": rag_focus_mode,
                    "generation_enabled": bool(run_generate),
                    "guardrail_enabled": bool(run_guardrail),
                    "uses_backend_nodes": True,
                    "uses_compiled_langgraph": False,
                },
                "embedding": embed_info,
                "backend_state": {
                    "retrieval_query": final_state.get("retrieval_query") or "",
                    "clinical_understanding": final_state.get("clinical_understanding") or {},
                    "query_expansion": query_expansion,
                    "sources": final_state.get("sources") or [],
                    "reasoning_steps": final_state.get("reasoning_steps") or [],
                    "rag_audit_payload": audit_payload,
                    "audit_id": final_state.get("audit_id") or audit_payload.get("audit_id") or "",
                    "guardrail_status": final_state.get("guardrail_status") or "",
                    "guardrail_reason": final_state.get("guardrail_reason") or "",
                },
                "retrieve": {
                    "legacy_k": int(cfg.retrieval_k),
                    "candidates_k": int(cfg.rag_retrieve_candidates_k),
                    "final_k": int(cfg.rag_retrieve_final_k),
                    "rewrite_query": final_state.get("retrieval_query") or query,
                    "expanded_query": query_expansion.get("expanded_query") or final_state.get("retrieval_query") or query,
                    "structured_terms": structured_terms,
                    "catalog_candidates": structured_terms.get("catalog_candidates") or query_expansion.get("catalog_candidates") or [],
                    "catalog_filter": {
                        "has_confident_catalog_candidate": catalog_filter.get("has_confident_catalog_candidate", False),
                        "documents_before_filter": catalog_filter.get("documents_before_filter")
                        or catalog_filter.get("candidate_count_before_filter")
                        or len(raw_candidates),
                        "documents_after_catalog_filter": catalog_filter.get("documents_after_catalog_filter")
                        or catalog_filter.get("candidate_count_after_filter"),
                        "documents_removed_by_catalog_filter": catalog_filter.get("documents_removed_by_catalog_filter") or [],
                        "catalog_filter_fallback": catalog_filter.get("catalog_filter_fallback", False),
                        "final_documents_count": catalog_filter.get("final_documents_count", len(docs)),
                        "returned_less_than_final_k": catalog_filter.get("returned_less_than_final_k", len(docs) < int(cfg.rag_retrieve_final_k)),
                    },
                    "dense_score_summary": dense_score_summary,
                    "final_score_summary": final_score_summary,
                    "final_results": [_doc_payload(doc, i + 1) for i, doc in enumerate(docs)],
                    "candidate_results": [
                        _candidate_payload(doc, score, i + 1)
                        for i, (doc, score) in enumerate(raw_candidates)
                    ],
                },
                "context": {"text": context_text or ""},
                "prompt": {"messages": prompt_messages or []},
                "generation": {
                    "enabled": bool(run_generate),
                    "answer": answer_text or "",
                    "model_requested": cfg.ollama_chat_model,
                    "model_used": generation_model_used or "",
                },
                "timing": asdict(timing),
                "errors": errors,
            }
            st.session_state["last_run"] = payload

        last = st.session_state.get("last_run")
        if last and isinstance(last, dict):
            payload = cast(dict[str, Any], last)
            errors = cast(list[str], payload.get("errors") or [])
            if errors:
                st.error("Ocorreram erros nesta execução:")
                for e in errors:
                    st.markdown(f"- {e}")

            st.divider()
            mode = cast(dict[str, Any], payload.get("mode") or {})
            st.subheader("✅ Execução")
            exec_cols = st.columns(4)
            exec_cols[0].metric("Modo", str(mode.get("name") or "-"))
            exec_cols[1].metric("Nodes backend", "sim" if mode.get("uses_backend_nodes") else "não")
            exec_cols[2].metric("LangGraph compilado", "sim" if mode.get("uses_compiled_langgraph") else "não")
            exec_cols[3].metric("Guardrail", "sim" if mode.get("guardrail_enabled") else "não")
            if not mode.get("uses_compiled_langgraph"):
                st.caption(
                    "Este painel chama os nodes reais do backend em sequência para expor scores, prompt e tempos. "
                    "Ele não usa o grafo compilado, porque o objetivo é inspecionar cada etapa."
                )

            backend_state = cast(dict[str, Any], payload.get("backend_state") or {})
            st.subheader("✅ Estado do backend")
            st.json(
                {
                    "retrieval_query": backend_state.get("retrieval_query") or "",
                    "clinical_understanding": backend_state.get("clinical_understanding") or {},
                    "query_expansion": backend_state.get("query_expansion") or {},
                    "sources": backend_state.get("sources") or [],
                    "reasoning_steps": backend_state.get("reasoning_steps") or [],
                    "audit_id": backend_state.get("audit_id") or "",
                    "guardrail_status": backend_state.get("guardrail_status") or "",
                    "guardrail_reason": backend_state.get("guardrail_reason") or "",
                },
                expanded=False,
            )

            st.subheader("✅ Retrieve detalhado (backend: expansão + Chroma + rerank)")
            retrieve_payload = cast(dict[str, Any], payload.get("retrieve") or {})
            rows = cast(list[dict[str, Any]], retrieve_payload.get("final_results") or [])
            candidate_rows = cast(list[dict[str, Any]], retrieve_payload.get("candidate_results") or [])
            st.caption(f"Query reescrita: `{retrieve_payload.get('rewrite_query') or ''}`")
            st.caption(f"Query expandida enviada ao Chroma: `{retrieve_payload.get('expanded_query') or ''}`")
            with st.expander("Structured terms e candidatos do catálogo", expanded=True):
                st.json(
                    {
                        "structured_terms": retrieve_payload.get("structured_terms") or {},
                        "catalog_candidates": retrieve_payload.get("catalog_candidates") or [],
                    },
                    expanded=False,
                )
            k_cols = st.columns(3)
            k_cols[0].metric("k candidatos", str(retrieve_payload.get("candidates_k") or "-"))
            k_cols[1].metric("k final", str(retrieve_payload.get("final_k") or "-"))
            k_cols[2].metric("candidatos Chroma", str(len(candidate_rows)))

            filter_payload = cast(dict[str, Any], retrieve_payload.get("catalog_filter") or {})
            f_cols = st.columns(5)
            f_cols[0].metric("catálogo confiante", "sim" if filter_payload.get("has_confident_catalog_candidate") else "não")
            f_cols[1].metric("antes filtro", str(filter_payload.get("documents_before_filter") or "-"))
            f_cols[2].metric("após filtro", str(filter_payload.get("documents_after_catalog_filter") or "-"))
            f_cols[3].metric("top final", str(filter_payload.get("final_documents_count") or len(rows)))
            f_cols[4].metric("fallback", "sim" if filter_payload.get("catalog_filter_fallback") else "não")
            if filter_payload.get("returned_less_than_final_k"):
                st.info("Retornou menos documentos que k final porque o filtro de catálogo removeu resultados incompatíveis.")
            removed = cast(list[dict[str, Any]], filter_payload.get("documents_removed_by_catalog_filter") or [])
            if removed:
                with st.expander("Documentos removidos pelo filtro de catálogo", expanded=False):
                    st.dataframe(
                        [
                            {
                                "disease": r.get("disease") or "",
                                "diretriz": r.get("diretriz") or "",
                                "section": r.get("section") or "",
                                "source_stem": r.get("source_stem") or "",
                                "dense_score": r.get("dense_score"),
                                "reason": r.get("reason") or "",
                            }
                            for r in removed
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )

            score_summary = cast(dict[str, Any] | None, retrieve_payload.get("final_score_summary"))
            if score_summary:
                score_cols = st.columns(4)
                score_cols[0].metric("best final", f"{float(score_summary['best']):.4f}")
                score_cols[1].metric("worst final", f"{float(score_summary['worst']):.4f}")
                score_cols[2].metric("spread final", f"{float(score_summary['spread']):.4f}")
                score_cols[3].metric("mean final", f"{float(score_summary['mean']):.4f}")
            if not rows:
                st.info("Sem resultados. Verifique se o Chroma tem vetores e se a coleção está correta.")
            else:
                st.dataframe(
                    [
                        {
                            "rank": r["rank"],
                            "final_score": r.get("final_score"),
                            "dense_score": r.get("dense_score"),
                            "dense_rank": r.get("dense_rank"),
                            "heuristic_score": r.get("heuristic_score"),
                            "cross_encoder_score": r.get("metadata", {}).get("cross_encoder_score"),
                            "source": r["source_label"],
                            "source_stem": (r.get("metadata") or {}).get("source_stem", ""),
                            "pages": f"{(r.get('metadata') or {}).get('page_start', '?')}-{(r.get('metadata') or {}).get('page_end', '?')}",
                            "ranking_reasons": ", ".join(str(x) for x in (r.get("ranking_reasons") or [])),
                            "preview": r["content_preview"].replace("\n", " "),
                        }
                        for r in rows
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

                with st.expander("Ver cada documento completo (conteúdo + metadados)", expanded=False):
                    for r in rows:
                        st.markdown(
                            f"**#{r['rank']} — final={r.get('final_score')!r} "
                            f"— dense={r.get('dense_score')!r} — {r['source_label']}**"
                        )
                        st.json(r.get("metadata") or {}, expanded=False)
                        st.text((r.get("content") or r.get("content_preview") or "").strip())
                        st.divider()

                with st.expander("Candidatos densos crus do Chroma antes do rerank", expanded=False):
                    dense_summary = cast(dict[str, Any] | None, retrieve_payload.get("dense_score_summary"))
                    if dense_summary:
                        st.caption(
                            "Resumo score denso: "
                            f"best={float(dense_summary['best']):.4f}, "
                            f"worst={float(dense_summary['worst']):.4f}, "
                            f"mean={float(dense_summary['mean']):.4f}"
                        )
                    st.dataframe(
                        [
                            {
                                "dense_rank": r["rank"],
                                "dense_score": r["dense_score"],
                                "source": r["source_label"],
                                "source_stem": (r.get("metadata") or {}).get("source_stem", ""),
                                "pages": f"{(r.get('metadata') or {}).get('page_start', '?')}-{(r.get('metadata') or {}).get('page_end', '?')}",
                                "preview": r["content_preview"].replace("\n", " "),
                            }
                            for r in candidate_rows
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )

            st.subheader("✅ Context assembly (como o contexto é montado)")
            st.text_area("Contexto montado", value=(payload.get("context") or {}).get("text") or "", height=220)

            st.subheader("✅ Prompt preview (mensagens enviadas ao LLM)")
            msgs = cast(list[dict[str, str]], (payload.get("prompt") or {}).get("messages") or [])
            if msgs:
                st.json(msgs, expanded=False)
            else:
                st.caption("Sem prompt (ainda).")

            st.subheader("✅ Generate analysis (qualidade e resultado)")
            gen = cast(dict[str, Any], payload.get("generation") or {})
            gen_enabled = bool(gen.get("enabled"))
            ans = gen.get("answer") or ""
            requested = gen.get("model_requested") or ""
            used = gen.get("model_used") or ""

            if not gen_enabled:
                st.info("Geração LLM desabilitada nesta execução (modo foco RAG ou opção manual).")
            else:
                if requested:
                    st.caption(f"Modelo usado: `{used or requested}`")
                if backend_state.get("guardrail_status"):
                    st.caption(
                        "Guardrail: "
                        f"`{backend_state.get('guardrail_status')}`"
                        f" | motivo: {backend_state.get('guardrail_reason') or '-'}"
                    )
                if ans:
                    st.text_area("Resposta gerada", value=ans, height=220)
                else:
                    st.warning("Geração habilitada, mas sem resposta final. Verifique erros acima.")

            if payload.get("embedding"):
                st.subheader("✅ Análise de embedding (vetor + stats)")
                emb = cast(dict[str, Any], payload["embedding"])
                st.json(
                    {
                        "token_count": emb.get("token_count"),
                        "stats": emb.get("stats"),
                        "vector_head": emb.get("vector_head"),
                        "vector_tail": emb.get("vector_tail"),
                    },
                    expanded=False,
                )

            if educational_mode:
                scores = [float(r.get("final_score") or r.get("dense_score") or 0.0) for r in rows]
                _render_educational_tips(
                    query=(payload.get("input") or {}).get("query") or "",
                    has_docs=bool(rows),
                    scores=scores,
                )

    with tab_vectorstore:
        st.subheader("Inspeção do Chroma (baixo nível)")
        st.caption("Aqui eu tento abrir o mesmo diretório e mostrar coleções e contagens.")
        try_open = st.button("Abrir e inspecionar", type="secondary")
        if try_open:
            try:
                import chromadb

                client = chromadb.PersistentClient(path=str(cfg.chroma_persist_dir))
                cols = client.list_collections()
                st.success(f"Coleções encontradas: {len(cols)}")
                st.dataframe(
                    [{"name": c.name, "metadata": c.metadata} for c in cols],
                    use_container_width=True,
                    hide_index=True,
                )
                if cfg.chroma_collection:
                    col = client.get_collection(name=str(cfg.chroma_collection))
                    st.metric("Coleção selecionada", str(cfg.chroma_collection))
                    try:
                        st.metric("Count", int(col.count()))
                    except Exception:
                        pass
                    with st.expander("Amostra (get) — primeiros 5", expanded=False):
                        sample = col.get(limit=5, include=["metadatas", "documents"])
                        st.json(sample, expanded=False)
            except Exception as exc:
                st.error(f"Falha ao inspecionar Chroma: {exc!s}")

    with tab_export:
        st.subheader("Export JSON (logs completos)")
        last = st.session_state.get("last_run")
        if not last:
            st.info("Rode o pipeline na aba anterior para gerar um payload exportável.")
        else:
            payload = cast(dict[str, Any], last)
            raw = json.dumps(payload, ensure_ascii=False, indent=2)
            st.download_button(
                "Baixar JSON da última execução",
                data=raw,
                file_name=f"rag-inspector-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json",
                mime="application/json",
            )
            st.text_area("Preview do JSON", value=raw[:12000], height=240)


if __name__ == "__main__":
    main()
