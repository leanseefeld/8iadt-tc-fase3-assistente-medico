#!/usr/bin/env python3
"""
RAG Inspector (standalone).

Objetivo: inspecionar embeddings, retrieve (Chroma), montagem de contexto/prompt e geração (Ollama)
sem iniciar a API/frontend.

Como rodar (venv ativo):
    cd llm && streamlit run scripts/rag_inspector_app.py
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any, cast

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

    class Settings:  # type: ignore[no-redef]
        pass

    def resolve_chroma_persist_dir(settings: Any) -> Path:  # type: ignore[no-redef]
        path = getattr(settings, "chroma_persist_dir", None)
        return Path(path) if path else vectorstore_chroma_dir()

    def _build_messages(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError("Dependências do RAG Inspector não instaladas.")

    async def generate_node(*args, **kwargs):  # type: ignore[no-redef]
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
    llm_stream_timeout_s: float


@dataclass(frozen=True)
class Timing:
    embed_ms: float | None
    retrieve_ms: float | None
    assemble_ms: float | None
    generate_ms: float | None


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


def _backend_settings(cfg: InspectorSettings, *, chat_model: str | None = None) -> Settings:
    return Settings(
        ollama_base_url=cfg.ollama_base_url,
        ollama_embed_model=cfg.ollama_embed_model,
        ollama_chat_model=chat_model or cfg.ollama_chat_model,
        chroma_persist_dir=Path(cfg.chroma_persist_dir),
        chroma_collection=cfg.chroma_collection,
        retrieval_k=int(cfg.retrieval_k),
        llm_stream_timeout_s=float(cfg.llm_stream_timeout_s),
    )


def _is_ollama_memory_error(exc: Exception) -> bool:
    txt = str(exc).lower()
    return (
        "requires more system memory" in txt
        or "status code: 500" in txt and "memory" in txt
        or "insufficient memory" in txt
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
            ollama_chat_model=st.text_input("Modelo de chat", value=cfg0.ollama_chat_model),
            chroma_persist_dir=st.text_input("Chroma persist dir", value=cfg0.chroma_persist_dir),
            chroma_collection=st.text_input("Chroma collection", value=cfg0.chroma_collection),
            retrieval_k=st.number_input("k (retrieval)", min_value=1, max_value=50, value=int(cfg0.retrieval_k), step=1),
            llm_stream_timeout_s=st.number_input("Timeout LLM (s)", min_value=5.0, max_value=600.0, value=float(cfg0.llm_stream_timeout_s), step=5.0),
        )
        auto_fallback_model = st.checkbox("Fallback automático para modelo leve", value=True)
        st.caption("Dica: o path default do Chroma é `vectorstore/chroma` na raiz do repositório.")

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
                options=["RAG apenas", "RAG + geração LLM"],
                index=0,
                horizontal=True,
            )
            rag_focus_mode = run_mode == "RAG apenas"
            run_generate = not rag_focus_mode
            educational_mode = st.checkbox("Modo educacional", value=True)
            debug_embed = st.checkbox("Analisar embedding (vetor + stats)", value=True)
            run_btn = st.button("Rodar pipeline", type="primary")

        with col_r:
            st.subheader("Flow diagram (atual)")
            flow_text = "backend.rewrite  →  backend.retrieve  →  backend.prompt_preview"
            if run_generate:
                flow_text = f"{flow_text}  →  backend.generate"
            st.code(flow_text, language="text")
            st.subheader("Performance (última execução)")
            last = st.session_state.get("last_run")
            if last and isinstance(last, dict):
                t = cast(dict[str, Any], last.get("timing") or {})
                st.metric("embed (ms)", f"{t.get('embed_ms'):.1f}" if t.get("embed_ms") is not None else "—")
                st.metric("retrieve (ms)", f"{t.get('retrieve_ms'):.1f}" if t.get("retrieve_ms") is not None else "—")
                st.metric("assemble (ms)", f"{t.get('assemble_ms'):.1f}" if t.get("assemble_ms") is not None else "—")
                if run_generate:
                    st.metric("generate (ms)", f"{t.get('generate_ms'):.1f}" if t.get("generate_ms") is not None else "—")
            else:
                st.caption("Rode uma vez para ver métricas.")

        if run_btn:
            errors: list[str] = []
            timing = Timing(embed_ms=None, retrieve_ms=None, assemble_ms=None, generate_ms=None)
            embed_info: dict[str, Any] | None = None
            retrieved: list[tuple[Document, float]] = []
            answer_text: str | None = None
            generation_model_used: str | None = None
            generation_fallback_used = False
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
                errors.append(f"Histórico JSON inválido; executando sem histórico: {exc!s}")

            # --- Load store ---
            try:
                store = _load_store(cfg)
            except Exception as exc:
                errors.append(f"Falha ao abrir Chroma: {exc!s}")
                store = None

            # --- Embedding analysis (optional) ---
            if debug_embed and query.strip():
                try:
                    emb = build_ollama_embeddings(model=cfg.ollama_embed_model, base_url=cfg.ollama_base_url)
                    t0 = time.perf_counter()
                    vec, n_tok = ollama_single_embed_with_token_count(emb, query)
                    timing = Timing(
                        embed_ms=(time.perf_counter() - t0) * 1000.0,
                        retrieve_ms=timing.retrieve_ms,
                        assemble_ms=timing.assemble_ms,
                        generate_ms=timing.generate_ms,
                    )
                    embed_info = {
                        "token_count": n_tok,
                        "stats": _vec_stats(vec),
                        "vector_head": vec[:32],
                        "vector_tail": vec[-8:] if len(vec) >= 8 else vec,
                    }
                except Exception as exc:
                    errors.append(f"Falha ao analisar embedding via Ollama: {exc!s}")

            # --- Backend rewrite + retrieve ---
            if store is not None and query.strip():
                try:
                    rewrite_out = cast(dict[str, Any], _run_async(rewrite_query_node(cast(Any, final_state), backend_settings)))
                    final_state.update(rewrite_out)

                    inspectable_store = InspectableStore(store)
                    t0 = time.perf_counter()
                    retrieve_out = retrieve_node(cast(Any, final_state), store=cast(Any, inspectable_store), settings=backend_settings)
                    timing = Timing(
                        embed_ms=timing.embed_ms,
                        retrieve_ms=(time.perf_counter() - t0) * 1000.0,
                        assemble_ms=timing.assemble_ms,
                        generate_ms=timing.generate_ms,
                    )
                    final_state.update(retrieve_out)
                    retrieved = inspectable_store.last_pairs
                except Exception as exc:
                    errors.append(f"Falha no retrieve do backend: {exc!s}")

            docs = cast(list[Document], final_state.get("retrieved_docs") or [d for d, _ in retrieved])
            scores = [float(s) for _, s in retrieved]

            # --- Backend context + prompt preview ---
            try:
                t0 = time.perf_counter()
                context_text = format_context_block(docs)
                messages = _build_messages(cast(Any, final_state))
                prompt_messages = [_message_to_payload(m) for m in messages]
                timing = Timing(
                    embed_ms=timing.embed_ms,
                    retrieve_ms=timing.retrieve_ms,
                    assemble_ms=(time.perf_counter() - t0) * 1000.0,
                    generate_ms=timing.generate_ms,
                )
            except Exception as exc:
                errors.append(f"Falha ao montar contexto/prompt: {exc!s}")

            # --- Backend generate (optional) ---
            if run_generate and query.strip():
                try:
                    t0 = time.perf_counter()
                    with st.status("Gerando resposta (streaming)...", expanded=False):
                        generate_out = cast(dict[str, Any], _run_async(generate_node(cast(Any, final_state), backend_settings)))
                    final_state.update(generate_out)
                    answer_text = str(final_state.get("answer") or "")
                    generation_model_used = cfg.ollama_chat_model
                    timing = Timing(
                        embed_ms=timing.embed_ms,
                        retrieve_ms=timing.retrieve_ms,
                        assemble_ms=timing.assemble_ms,
                        generate_ms=(time.perf_counter() - t0) * 1000.0,
                    )
                except Exception as exc:
                    if auto_fallback_model and _is_ollama_memory_error(exc) and fallback_model_name.strip():
                        try:
                            fallback_name = fallback_model_name.strip()
                            fallback_settings = _backend_settings(cfg, chat_model=fallback_name)
                            t0 = time.perf_counter()
                            with st.status(
                                f"Modelo principal sem memória; tentando fallback `{fallback_name}`...",
                                expanded=False,
                            ):
                                generate_out = cast(
                                    dict[str, Any],
                                    _run_async(generate_node(cast(Any, final_state), fallback_settings)),
                                )
                            final_state.update(generate_out)
                            answer_text = str(final_state.get("answer") or "")
                            generation_model_used = fallback_name
                            generation_fallback_used = True
                            timing = Timing(
                                embed_ms=timing.embed_ms,
                                retrieve_ms=timing.retrieve_ms,
                                assemble_ms=timing.assemble_ms,
                                generate_ms=(time.perf_counter() - t0) * 1000.0,
                            )
                            errors.append(
                                "Modelo principal sem memória; resposta gerada com fallback "
                                f"`{fallback_name}`."
                            )
                        except Exception as fallback_exc:
                            errors.append(
                                "Falha na geração do backend: "
                                f"{exc!s}. Fallback `{fallback_model_name.strip()}` também falhou: {fallback_exc!s}"
                            )
                    else:
                        errors.append(f"Falha na geração do backend: {exc!s}")

            payload: dict[str, Any] = {
                "timestamp": _now_iso(),
                "settings": asdict(cfg),
                "input": {"query": query, "chat_history": final_state.get("chat_history") or []},
                "mode": {"rag_focus_mode": rag_focus_mode},
                "embedding": embed_info,
                "backend_state": {
                    "retrieval_query": final_state.get("retrieval_query") or "",
                    "sources": final_state.get("sources") or [],
                    "reasoning_steps": final_state.get("reasoning_steps") or [],
                },
                "retrieve": {
                    "k": int(cfg.retrieval_k),
                    "results": [
                        {
                            "rank": i + 1,
                            "score": float(score),
                            "source_label": format_source_label(doc),
                            "doc_id": getattr(doc, "id", None),
                            "metadata": doc.metadata,
                            "content_preview": (doc.page_content or "").strip()[:500],
                            "content": (doc.page_content or "").strip(),
                        }
                        for i, (doc, score) in enumerate(retrieved)
                    ],
                },
                "context": {"text": context_text or ""},
                "prompt": {"messages": prompt_messages or []},
                "generation": {
                    "enabled": bool(run_generate),
                    "answer": answer_text or "",
                    "model_requested": cfg.ollama_chat_model,
                    "model_used": generation_model_used or "",
                    "fallback_used": generation_fallback_used,
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
            backend_state = cast(dict[str, Any], payload.get("backend_state") or {})
            st.subheader("✅ Estado do backend")
            st.json(
                {
                    "retrieval_query": backend_state.get("retrieval_query") or "",
                    "sources": backend_state.get("sources") or [],
                    "reasoning_steps": backend_state.get("reasoning_steps") or [],
                },
                expanded=False,
            )

            st.subheader("✅ Retrieve detalhado (docs + score)")
            rows = cast(list[dict[str, Any]], (payload.get("retrieve") or {}).get("results") or [])
            if not rows:
                st.info("Sem resultados. Verifique se o Chroma tem vetores e se a coleção está correta.")
            else:
                st.dataframe(
                    [
                        {
                            "rank": r["rank"],
                            "score": r["score"],
                            "source": r["source_label"],
                            "source_stem": (r.get("metadata") or {}).get("source_stem", ""),
                            "pages": f"{(r.get('metadata') or {}).get('page_start', '?')}-{(r.get('metadata') or {}).get('page_end', '?')}",
                            "preview": r["content_preview"].replace("\n", " "),
                        }
                        for r in rows
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

                with st.expander("Ver cada documento completo (conteúdo + metadados)", expanded=False):
                    for r in rows:
                        st.markdown(f"**#{r['rank']} — score={r['score']!r} — {r['source_label']}**")
                        st.json(r.get("metadata") or {}, expanded=False)
                        st.text((r.get("content") or r.get("content_preview") or "").strip())
                        st.divider()

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
                    if gen.get("fallback_used"):
                        st.caption(f"Modelo solicitado: `{requested}` | modelo usado: `{used}` (fallback)")
                    else:
                        st.caption(f"Modelo usado: `{used or requested}`")
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
                scores = [float(r.get("score") or 0.0) for r in rows]
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
