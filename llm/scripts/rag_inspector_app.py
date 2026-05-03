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
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import streamlit as st

IMPORT_ERROR: ModuleNotFoundError | None = None
try:
    from langchain_core.documents import Document
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_ollama import ChatOllama
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
    HumanMessage = Any  # type: ignore[assignment]
    SystemMessage = Any  # type: ignore[assignment]
    ChatOllama = Any  # type: ignore[assignment]
    CHROMA_COLLECTION_PCDT = "pcdt"

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
    llm_temperature: float
    llm_stream_timeout_s: float


@dataclass(frozen=True)
class Timing:
    embed_ms: float | None
    retrieve_ms: float | None
    assemble_ms: float | None
    generate_ms: float | None


def _default_settings() -> InspectorSettings:
    # Alinha defaults com backend/src/assistente_medico_api/config.py (prefixo MEDICO_)
    base_url = (os.environ.get("MEDICO_OLLAMA_BASE_URL") or os.environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").strip()
    embed_model = (os.environ.get("MEDICO_OLLAMA_EMBED_MODEL") or "nomic-embed-text").strip()
    chat_model = (os.environ.get("MEDICO_OLLAMA_CHAT_MODEL") or "gemma4:e4b-it-q4_K_M").strip()
    chroma_dir = os.environ.get("MEDICO_CHROMA_PERSIST_DIR") or str(vectorstore_chroma_dir())
    collection = (os.environ.get("MEDICO_CHROMA_COLLECTION") or CHROMA_COLLECTION_PCDT).strip()
    k = int(os.environ.get("MEDICO_RETRIEVAL_K") or "6")
    timeout_s = float(os.environ.get("MEDICO_LLM_STREAM_TIMEOUT_S") or "120")
    return InspectorSettings(
        ollama_base_url=base_url,
        ollama_embed_model=embed_model,
        ollama_chat_model=chat_model,
        chroma_persist_dir=chroma_dir,
        chroma_collection=collection,
        retrieval_k=k,
        llm_temperature=0.2,
        llm_stream_timeout_s=timeout_s,
    )


def _format_source_label(doc: Document) -> str:
    meta = doc.metadata or {}
    stem = meta.get("source_stem", "?")
    p0 = meta.get("page_start", "?")
    p1 = meta.get("page_end", "?")
    return f"PCDT {stem} (pp. {p0}-{p1})"


def _format_context_block(docs: list[Document]) -> str:
    parts: list[str] = []
    for i, doc in enumerate(docs, start=1):
        meta = doc.metadata or {}
        stem = meta.get("source_stem", "?")
        p0 = meta.get("page_start", "?")
        p1 = meta.get("page_end", "?")
        header = f"[{i}] PCDT stem={stem} págs. {p0}-{p1}"
        parts.append(f"{header}\n{(doc.page_content or '').strip()}")
    return "\n\n---\n\n".join(parts)


_SYSTEM_PROMPT = """\
Você é um assistente clínico de apoio a médicos no Brasil.
Use o contexto dos Protocolos Clínicos e Diretrizes Terapêuticas (PCDT) fornecido abaixo quando for relevante.
Cite as fontes pelo identificador [n] correspondente ao trecho.
Recomende mas não prescreva medicamentos, doses ou esquemas terapêuticos específicos: o médico responsável decide.
Se o contexto não for suficiente, diga claramente e evite inventar dados clínicos.
Responda em português do Brasil, de forma objetiva e profissional.\
"""


def _build_prompt_messages(*, query: str, docs: list[Document]) -> list[Any]:
    context = _format_context_block(docs) if docs else "(Nenhum trecho recuperado.)"
    human = (
        f"Pergunta do médico:\n{query}\n\n"
        f"Contexto (trechos PCDT):\n{context}\n\n"
        "Responda com base no contexto quando aplicável."
    )
    return [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human)]


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


def _is_ollama_memory_error(exc: Exception) -> bool:
    txt = str(exc).lower()
    return (
        "requires more system memory" in txt
        or "status code: 500" in txt and "memory" in txt
        or "insufficient memory" in txt
    )


def _load_store(cfg: InspectorSettings):
    embeddings = build_ollama_embeddings(model=cfg.ollama_embed_model, base_url=cfg.ollama_base_url)
    return open_chroma_vectorstore(
        persist_directory=Path(cfg.chroma_persist_dir),
        embedding_function=embeddings,
        collection_name=cfg.chroma_collection,
    )


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
            llm_temperature=st.slider("Temperatura", min_value=0.0, max_value=1.0, value=float(cfg0.llm_temperature), step=0.05),
            llm_stream_timeout_s=st.number_input("Timeout LLM (s)", min_value=5.0, max_value=600.0, value=float(cfg0.llm_stream_timeout_s), step=5.0),
        )
        auto_fallback_model = st.checkbox("Fallback automático para modelo leve", value=True)
        fallback_model_name = st.text_input("Modelo fallback (leve)", value="llama3.2:3b")
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
            flow_text = "embed_query  →  retrieve  →  context_assembly  →  prompt_preview"
            if run_generate:
                flow_text = f"{flow_text}  →  generate"
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

            # --- Retrieve ---
            if store is not None and query.strip():
                try:
                    t0 = time.perf_counter()
                    retrieved = cast(list[tuple[Document, float]], store.similarity_search_with_score(query, k=int(cfg.retrieval_k)))
                    timing = Timing(
                        embed_ms=timing.embed_ms,
                        retrieve_ms=(time.perf_counter() - t0) * 1000.0,
                        assemble_ms=timing.assemble_ms,
                        generate_ms=timing.generate_ms,
                    )
                except Exception as exc:
                    errors.append(f"Falha no retrieve (similarity_search_with_score): {exc!s}")

            docs = [d for d, _ in retrieved]
            scores = [float(s) for _, s in retrieved]

            # --- Assemble context + prompt preview ---
            try:
                t0 = time.perf_counter()
                context_text = _format_context_block(docs)
                messages = _build_prompt_messages(query=query, docs=docs)
                prompt_messages = []
                for m in messages:
                    if isinstance(m, SystemMessage):
                        prompt_messages.append({"role": "system", "content": m.content})
                    elif isinstance(m, HumanMessage):
                        prompt_messages.append({"role": "user", "content": m.content})
                    else:
                        prompt_messages.append({"role": "message", "content": getattr(m, "content", str(m))})
                timing = Timing(
                    embed_ms=timing.embed_ms,
                    retrieve_ms=timing.retrieve_ms,
                    assemble_ms=(time.perf_counter() - t0) * 1000.0,
                    generate_ms=timing.generate_ms,
                )
            except Exception as exc:
                errors.append(f"Falha ao montar contexto/prompt: {exc!s}")

            # --- Generate (optional) ---
            if run_generate and query.strip():
                try:
                    import httpx

                    timeout = httpx.Timeout(float(cfg.llm_stream_timeout_s), connect=10.0)
                    llm = ChatOllama(
                        model=cfg.ollama_chat_model,
                        base_url=cfg.ollama_base_url,
                        temperature=float(cfg.llm_temperature),
                        async_client_kwargs={"timeout": timeout},
                        client_kwargs={"timeout": timeout},
                    )
                    t0 = time.perf_counter()
                    pieces: list[str] = []
                    with st.status("Gerando resposta (streaming)...", expanded=False):
                        for chunk in llm.stream(_build_prompt_messages(query=query, docs=docs)):
                            piece = getattr(chunk, "content", None)
                            if isinstance(piece, list):
                                piece = "".join(str(p) for p in piece)
                            if piece:
                                pieces.append(str(piece))
                    answer_text = "".join(pieces)
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
                            import httpx

                            timeout = httpx.Timeout(float(cfg.llm_stream_timeout_s), connect=10.0)
                            llm = ChatOllama(
                                model=fallback_model_name.strip(),
                                base_url=cfg.ollama_base_url,
                                temperature=float(cfg.llm_temperature),
                                async_client_kwargs={"timeout": timeout},
                                client_kwargs={"timeout": timeout},
                            )
                            t0 = time.perf_counter()
                            pieces = []
                            with st.status(
                                f"Modelo principal sem memória; tentando fallback `{fallback_model_name.strip()}`...",
                                expanded=False,
                            ):
                                for chunk in llm.stream(_build_prompt_messages(query=query, docs=docs)):
                                    piece = getattr(chunk, "content", None)
                                    if isinstance(piece, list):
                                        piece = "".join(str(p) for p in piece)
                                    if piece:
                                        pieces.append(str(piece))
                            answer_text = "".join(pieces)
                            generation_model_used = fallback_model_name.strip()
                            generation_fallback_used = True
                            timing = Timing(
                                embed_ms=timing.embed_ms,
                                retrieve_ms=timing.retrieve_ms,
                                assemble_ms=timing.assemble_ms,
                                generate_ms=(time.perf_counter() - t0) * 1000.0,
                            )
                            errors.append(
                                "Modelo principal sem memória; resposta gerada com fallback "
                                f"`{fallback_model_name.strip()}`."
                            )
                        except Exception as fallback_exc:
                            errors.append(
                                "Falha na geração (ChatOllama): "
                                f"{exc!s}. Fallback `{fallback_model_name.strip()}` também falhou: {fallback_exc!s}"
                            )
                    else:
                        errors.append(f"Falha na geração (ChatOllama): {exc!s}")

            payload: dict[str, Any] = {
                "timestamp": _now_iso(),
                "settings": asdict(cfg),
                "input": {"query": query},
                "mode": {"rag_focus_mode": rag_focus_mode},
                "embedding": embed_info,
                "retrieve": {
                    "k": int(cfg.retrieval_k),
                    "results": [
                        {
                            "rank": i + 1,
                            "score": float(score),
                            "source_label": _format_source_label(doc),
                            "doc_id": getattr(doc, "id", None),
                            "metadata": doc.metadata,
                            "content_preview": (doc.page_content or "").strip()[:500],
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
                        st.text((r.get("content_preview") or "").strip())
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

