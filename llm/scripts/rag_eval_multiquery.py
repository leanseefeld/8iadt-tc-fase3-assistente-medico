#!/usr/bin/env python3
"""Avaliação comparativa: 1-query vs N-query (CoT) vs RRF vs 1q+Nq.

Mede hit-rate@k / recall do ``expected_source_stem`` sobre um conjunto curado de
perguntas clínicas, comparando quatro caminhos:
  - 1q:    ``similarity_search_with_score(pergunta, k)`` — baseline
  - Nq:    union de todos os resultados individuais das N queries geradas via CoT
  - RRF:   fusão das N queries por Reciprocal Rank Fusion
  - 1q+Nq: RRF de [pergunta original + N queries CoT] — explora se a pergunta
           direta complementa as queries estruturadas pelo planner

Como rodar (da raiz do repo, com o venv do backend ativo):

    uv run --project backend python llm/scripts/rag_eval_multiquery.py

    Opções:
      --k 10                    top-k avaliado (default: rag_retrieve_final_k do .env)
      --with-history            usa o dataset com histórico de conversa (perguntas de
                                acompanhamento que dependem do contexto anterior)
      --eval-file path/to.jsonl JSONL alternativo de perguntas (sobrescreve --with-history)
      --env-file path/to/.env   .env alternativo (default: backend/.env)
      --docs [N]                exibe top N chunks do caminho RRF (default N=6)
      --docs-single [N]         exibe top N chunks do caminho 1-query (default N=6)
      --docs-nq [N]             exibe top N chunks do caminho Nq (union, por dist_score)
      --docs-combined [N]       exibe top N chunks do caminho 1q+Nq (default N=6)
                                ambos: --docs → top 6; --docs 10 → top 10

Pré-requisitos:
  - Chroma populado (``uv run --project llm build-vectorstore``)
  - Ollama rodando com ``nomic-embed-text`` (para embeddings de query)
  - LLM de chat acessível (omlx ou Ollama) conforme ``backend/.env``
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPO_ROOT / "backend" / ".env"

for src_path in (REPO_ROOT / "backend" / "src", REPO_ROOT / "llm" / "src"):
    s = str(src_path)
    if s not in sys.path:
        sys.path.insert(0, s)

from langchain_core.documents import Document  # noqa: E402
from rich.columns import Columns  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402
from rich import box  # noqa: E402

from assistente_medico_api.config import Settings  # noqa: E402
from assistente_medico_api.graph.search.nodes import plan_queries_node, search_node  # noqa: E402
from pcdt_ingest.embed import (  # noqa: E402
    CHROMA_COLLECTION_PCDT,
    build_ollama_embeddings,
    open_chroma_vectorstore,
)
from pcdt_ingest.paths import vectorstore_chroma_dir  # noqa: E402

DEFAULT_EVAL_FILE = REPO_ROOT / "llm" / "eval" / "rag_questions.jsonl"
DEFAULT_EVAL_FILE_HISTORY = REPO_ROOT / "llm" / "eval" / "rag_questions_history.jsonl"
DEFAULT_RUNS_DIR = REPO_ROOT / "llm" / "eval" / "runs"

console = Console(highlight=False)


# ── helpers ──────────────────────────────────────────────────────────────────

def load_store():
    return open_chroma_vectorstore(
        persist_directory=vectorstore_chroma_dir(),
        embedding_function=build_ollama_embeddings(),
        collection_name=CHROMA_COLLECTION_PCDT,
    )


def load_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def _stems(docs: list[Document]) -> list[str]:
    return [str((d.metadata or {}).get("source_stem", "")) for d in docs]


def _hit(docs: list[Document], expected_stem: str) -> bool:
    return bool(expected_stem) and expected_stem in _stems(docs)


def _section_label(meta: dict) -> str:
    section = meta.get("section") or ""
    if section:
        return section
    h1 = meta.get("header_1") or ""
    h2 = meta.get("header_2") or ""
    if h1 and h2:
        return f"{h1} > {h2}"
    return h1 or h2 or "—"


def _section_cell(meta: dict) -> Text:
    """Empilha section / header_1 / header_2 numa célula, cada campo truncado em 10 chars."""
    _T = 10

    def _trunc(v: str) -> str:
        return v[:_T] + "…" if len(v) > _T else v

    fields = [
        ("s", meta.get("section") or ""),
        ("1", meta.get("header_1") or ""),
        ("2", meta.get("header_2") or ""),
    ]
    t = Text()
    first = True
    for label, val in fields:
        if not val:
            continue
        if not first:
            t.append("\n")
        t.append(f"{label}:", style="dim")
        t.append(_trunc(val))
        first = False
    return t if not first else Text("—", style="dim")


def _doc_detail(doc: Document, score: float, label: str) -> dict:
    meta = doc.metadata or {}
    return {
        "label": label,
        "source_stem": meta.get("source_stem", "?"),
        "section": _section_label(meta),
        "page_start": meta.get("page_start", "?"),
        "page_end": meta.get("page_end", "?"),
        "chunk_index": meta.get("chunk_index", "?"),
        "score": round(score, 6),
    }


def single_query_docs(store, question: str, k: int) -> tuple[list[Document], list[tuple[Document, float]]]:
    pairs = store.similarity_search_with_score(question, k=k)
    docs = [doc for doc, _ in pairs]
    scored = [(doc, float(score)) for doc, score in pairs]
    return docs, scored


async def multi_query_docs(
    store, settings: Settings, question: str, k: int,
    chat_history: list[dict] | None = None,
) -> tuple[
    list[Document],      # rrf_docs
    list[str],           # queries
    str,                 # llm_reasoning
    str,                 # raw_llm
    str | None,          # plan_error
    str | None,          # llm_parse_error
    list[tuple[Document, float]],  # rrf_scored
    list[Document],      # nq_union_docs
    list[Document],      # combined_docs (1q+Nq)
    list[tuple[Document, float]],  # combined_scored
    list[str],           # combined_queries
]:
    """Retorna rrf_docs, queries, reasoning, raw_llm, plan_error, llm_parse_error, rrf_scored, nq_union_docs, combined_docs, combined_scored, combined_queries.

    rrf_docs / rrf_scored — resultado da fusão RRF (caminho RRF).
    nq_union_docs         — union de todos os resultados individuais das N queries (caminho Nq).
    """
    plan_state: dict = {"query": question, "reasoning_steps": []}
    if chat_history:
        plan_state["chat_history"] = chat_history
    plan = await plan_queries_node(plan_state, settings)
    debug = plan.get("multi_query_debug") or {}
    queries = plan.get("search_queries") or [question]
    llm_reasoning = debug.get("reasoning") or ""
    raw_llm = debug.get("raw") or ""
    plan_error = debug.get("error")
    llm_parse_error = debug.get("parse_error")

    # Coleta resultados por-query para o caminho Nq (union, top-k cada).
    # Mantém a melhor dist_score de qualquer query para cada doc.
    nq_seen: dict[str, Document] = {}
    nq_scored_map: dict[str, float] = {}
    for q in queries:
        pairs = store.similarity_search_with_score(q, k=k)
        for doc, score in pairs:
            key = _doc_key_eval(doc)
            if key not in nq_seen or float(score) > nq_scored_map[key]:
                nq_seen[key] = doc
                nq_scored_map[key] = float(score)
    nq_union_docs = list(nq_seen.values())
    nq_union_scored = [(nq_seen[key], nq_scored_map[key]) for key in nq_seen]

    # Fusão RRF via search_node (usa rag_retrieve_candidates_k internamente).
    out = search_node({"search_queries": queries, "reasoning_steps": []}, store=store, settings=settings)
    fused: list[Document] = out.get("retrieved_docs") or []
    rrf_scored = [(doc, float((doc.metadata or {}).get("rrf_score", 0.0))) for doc in fused]

    # 1q+Nq: RRF de [pergunta original + queries CoT]. A pergunta entra primeiro.
    q_lower = question.strip().lower()
    combined_queries = [question] + [q for q in queries if q.strip().lower() != q_lower]
    out_combined = search_node(
        {"search_queries": combined_queries, "reasoning_steps": []}, store=store, settings=settings
    )
    combined_docs: list[Document] = out_combined.get("retrieved_docs") or []
    combined_scored = [(doc, float((doc.metadata or {}).get("rrf_score", 0.0))) for doc in combined_docs]

    return fused, queries, llm_reasoning, raw_llm, plan_error, llm_parse_error, rrf_scored, nq_union_docs, combined_docs, combined_scored, combined_queries


def _write_run_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ── rich rendering ────────────────────────────────────────────────────────────

def _hit_badge(hit: bool) -> Text:
    return Text(" OK ", style="bold white on dark_green") if hit else Text(" -- ", style="bold white on red")


def _doc_key_eval(doc: Document) -> str:
    if getattr(doc, "id", None):
        return str(doc.id)
    meta = doc.metadata or {}
    return f"{meta.get('source_stem', '?')}:{meta.get('chunk_index', meta.get('page_start', '?'))}"


def _build_champion_map(store, queries: list[str]) -> dict[str, list[str]]:
    """Para cada query, acha o doc #1 e marca-o como campeão dessa query."""
    champ: dict[str, list[str]] = {}
    for i, q in enumerate(queries, 1):
        pairs = store.similarity_search_with_score(q, k=1)
        if pairs:
            key = _doc_key_eval(pairs[0][0])
            champ.setdefault(key, []).append(f"q{i}")
    return champ


def _docs_table(
    scored: list[tuple[Document, float]],
    top_n: int,
    score_col: str,
    champion_map: dict[str, list[str]] | None = None,
    expected_stem: str = "",
) -> Table:
    all_ranked = sorted(scored, key=lambda x: x[1], reverse=True)
    visible = list(all_ranked[:top_n])

    # Se o esperado existe nos resultados mas ficou fora do top_n, anexa ao final.
    if expected_stem:
        in_visible = any(
            str((d.metadata or {}).get("source_stem", "?")) == expected_stem
            for d, _ in visible
        )
        if not in_visible:
            for real_rank, (doc, score) in enumerate(all_ranked[top_n:], start=top_n + 1):
                if str((doc.metadata or {}).get("source_stem", "?")) == expected_stem:
                    visible.append((doc, score, real_rank))  # type: ignore[arg-type]
                    break

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan", pad_edge=False)
    t.add_column("#", style="dim", width=3, justify="right")
    t.add_column("stem", no_wrap=True, max_width=36)
    t.add_column("pp", justify="center", width=7)
    t.add_column(score_col, justify="right", width=10)
    t.add_column("seção", style="white", max_width=36, no_wrap=True)
    if champion_map is not None:
        t.add_column("campeão", max_width=14)
    for display_i, entry in enumerate(visible, start=1):
        doc, score = entry[0], entry[1]
        real_rank: int | None = entry[2] if len(entry) == 3 else None  # type: ignore[misc]
        meta = doc.metadata or {}
        stem = str(meta.get("source_stem", "?"))
        is_expected = bool(expected_stem) and stem == expected_stem
        rank_str = str(real_rank) if real_rank is not None else str(display_i)
        rank_cell = Text(rank_str, style="bold dark_green" if is_expected else "dim")
        stem_cell = Text(stem, style="bold dark_green" if is_expected else "yellow")
        pages = f"{meta.get('page_start', '?')}-{meta.get('page_end', '?')}"
        section = _section_label(meta)
        score_str = f"{score:.6f}"
        if champion_map is not None:
            labels = champion_map.get(_doc_key_eval(doc), [])
            if labels:
                champ_cell = Text()
                for j, lbl in enumerate(labels):
                    if j:
                        champ_cell.append(" ")
                    champ_cell.append(lbl, style="bold magenta")
            else:
                champ_cell = Text("", style="dim")
            t.add_row(rank_cell, stem_cell, pages, score_str, section, champ_cell)
        else:
            t.add_row(rank_cell, stem_cell, pages, score_str, section)
    return t


def _queries_text(queries: list[str]) -> Text:
    t = Text()
    for i, q in enumerate(queries, 1):
        t.append(f"  q{i} ", style="bold magenta")
        t.append(q + "\n", style="white")
    return t


def _reasoning_panel(reasoning: str) -> Panel:
    return Panel(
        reasoning,
        title="[dim]raciocínio CoT[/dim]",
        border_style="dim",
        padding=(0, 1),
    )


# ── main loop ─────────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> int:
    env_file = Path(args.env_file)
    if not env_file.exists():
        console.print(f"[yellow]AVISO:[/yellow] .env não encontrado em {env_file} — usando shell env.")
    settings = Settings(_env_file=str(env_file))
    extras: list[str] = []
    if settings.llm_repetition_penalty is not None:
        extras.append(f"rep_penalty=[cyan]{settings.llm_repetition_penalty}[/cyan]")
    if settings.rag_multi_query_min_p is not None:
        extras.append(f"min_p=[cyan]{settings.rag_multi_query_min_p}[/cyan]")
    if settings.rag_multi_query_max_tokens is not None:
        extras.append(f"max_tokens=[cyan]{settings.rag_multi_query_max_tokens}[/cyan]")
    extras_str = ("  " + "  ".join(extras)) if extras else ""
    console.print(
        f"[dim]LLM:[/dim] provider=[cyan]{settings.llm_chat_provider}[/cyan]"
        f"  model=[cyan]{settings.llm_chat_model}[/cyan]"
        f"  temperature=[cyan]{settings.llm_temperature}[/cyan]"
        f"{extras_str}"
        f"  base_url=[dim]{settings.openai_base_url}[/dim]",
        highlight=False,
    )

    k = int(args.k or settings.rag_retrieve_final_k)
    show_rrf: int | None = args.docs
    show_single: int | None = args.docs_single
    show_nq: int | None = args.docs_nq
    show_combined: int | None = args.docs_combined
    store = load_store()

    # Seleção do dataset: --eval-file (explícito) > --with-history > padrão sem histórico.
    if args.eval_file is not None:
        eval_file = Path(args.eval_file)
    elif args.with_history:
        eval_file = DEFAULT_EVAL_FILE_HISTORY
    else:
        eval_file = DEFAULT_EVAL_FILE
    console.print(f"[dim]Dataset:[/dim] {eval_file.name}")
    cases = load_cases(eval_file)

    run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    runs_dir = Path(args.runs_dir)
    run_file = runs_dir / f"run_{run_ts}.jsonl"

    single_hits = 0
    nq_hits = 0
    rrf_hits = 0
    combined_hits = 0
    parse_errors = 0  # LLM respondeu mas o JSON não pôde ser parseado.
    records: list[dict] = []

    console.print()
    console.rule(f"[bold]Avaliando {len(cases)} perguntas  k={k}[/bold]")
    console.print()

    for idx, case in enumerate(cases, start=1):
        question = case["question"]
        expected = case.get("expected_source_stem", "")
        chat_history = case.get("chat_history") or None

        t0 = time.perf_counter()
        s_docs, s_scored = single_query_docs(store, question, k)
        single_ms = round((time.perf_counter() - t0) * 1000, 1)

        t1 = time.perf_counter()
        (
            rrf_docs, queries, llm_reasoning, raw_llm, plan_error, llm_parse_error,
            rrf_scored, nq_union_docs,
            combined_docs, combined_scored, combined_queries,
        ) = await multi_query_docs(store, settings, question, k, chat_history)
        multi_ms = round((time.perf_counter() - t1) * 1000, 1)

        s_hit = _hit(s_docs, expected)
        nq_hit = _hit(nq_union_docs, expected)
        rrf_hit = _hit(rrf_docs, expected)
        combined_hit = _hit(combined_docs, expected)
        single_hits += int(s_hit)
        nq_hits += int(nq_hit)
        rrf_hits += int(rrf_hit)
        combined_hits += int(combined_hit)

        # ── question header ──
        header = Text()
        header.append(f"{idx:>2}. ", style="bold dim")
        header.append(question, style="bold white")
        console.print(header)

        # ── histórico da conversa (quando presente no dataset) ──
        if chat_history:
            for turn in chat_history:
                role = turn.get("role", "?")
                speaker = "Médico" if role == "user" else "Assistente"
                hist_line = Text("    ")
                hist_line.append(f"{speaker}: ", style="dim cyan")
                hist_line.append((turn.get("content") or "").strip(), style="dim")
                console.print(hist_line)

        # ── expected / hit badges ──
        meta_line = Text("    ")
        meta_line.append("esperado ", style="dim")
        meta_line.append(expected or "—", style="bold yellow")
        meta_line.append("  1q ", style="dim")
        meta_line.append_text(_hit_badge(s_hit))
        meta_line.append("  Nq ", style="dim")
        meta_line.append_text(_hit_badge(nq_hit))
        meta_line.append("  RRF ", style="dim")
        meta_line.append_text(_hit_badge(rrf_hit))
        meta_line.append("  1q+Nq ", style="dim")
        meta_line.append_text(_hit_badge(combined_hit))
        meta_line.append(f"  {len(queries)} queries  ", style="dim")
        meta_line.append(f"{multi_ms:.0f}ms", style="dim")
        console.print(meta_line)

        # ── CoT / raw fallback ──
        parse_error = bool(raw_llm) and not llm_reasoning and not plan_error
        if parse_error:
            parse_errors += 1
        if llm_reasoning:
            console.print(_reasoning_panel(llm_reasoning), style="dim")
        elif raw_llm:
            available = console.width - 4
            raw_line = raw_llm.replace("\n", " ")
            truncated = raw_line[:available - 1] + "…" if len(raw_line) > available else raw_line
            console.print(f"  [red]{truncated}[/red]")
            if llm_parse_error:
                console.print(f"  [bold red]parse:[/bold red] [red]{llm_parse_error}[/red]")

        # ── generated queries ──
        console.print(_queries_text(queries))

        if plan_error:
            console.print(f"  [bold red]ERRO plano:[/bold red] {plan_error}")

        # ── doc tables ──
        if show_single is not None:
            console.print(
                f"  [bold blue]1-query[/bold blue]"
                f"[dim]  top {show_single}  ↑ dist_score[/dim]"
            )
            console.print(_docs_table(s_scored, show_single, "dist_score", expected_stem=expected))

        if show_nq is not None:
            nq_scored = [
                (doc, float((doc.metadata or {}).get("rrf_score") or 0.0)
                 if (doc.metadata or {}).get("rrf_score") is not None
                 else next(
                     (sc for d2, sc in rrf_scored if _doc_key_eval(d2) == _doc_key_eval(doc)),
                     0.0,
                 ))
                for doc in nq_union_docs
            ]
            # Usa a melhor dist_score disponível via nova busca por-query.
            nq_scored_final = [
                (doc, max(
                    (sc for d2, sc in s_scored if _doc_key_eval(d2) == _doc_key_eval(doc)),
                    default=0.0,
                ))
                for doc in nq_union_docs
            ]
            console.print(
                f"  [bold yellow]Nq (union)[/bold yellow]"
                f"[dim]  top {show_nq}  ↑ dist_score[/dim]"
            )
            console.print(_docs_table(nq_scored_final, show_nq, "dist_score", expected_stem=expected))

        if show_rrf is not None:
            champion_map = _build_champion_map(store, queries)
            console.print(
                f"  [bold cyan]RRF[/bold cyan]"
                f"[dim]  top {show_rrf}  ↑ rrf_score[/dim]"
            )
            console.print(_docs_table(rrf_scored, show_rrf, "rrf_score", champion_map, expected))

        if show_combined is not None:
            combined_champ = _build_champion_map(store, combined_queries)
            console.print(
                f"  [bold green]1q+Nq[/bold green]"
                f"[dim]  top {show_combined}  ↑ rrf_score  ({len(combined_queries)} queries)[/dim]"
            )
            console.print(_docs_table(combined_scored, show_combined, "rrf_score", combined_champ, expected))

        console.rule(style="dim")

        records.append({
            "run_ts": run_ts,
            "idx": idx,
            "question": question,
            "chat_history": chat_history or [],
            "expected_source_stem": expected,
            "single_query_hit": s_hit,
            "nq_hit": nq_hit,
            "rrf_hit": rrf_hit,
            "generated_queries": queries,
            "llm_reasoning": llm_reasoning,
            "raw_llm": raw_llm,
            "plan_error": plan_error,
            "llm_parse_error": llm_parse_error,
            "parse_error": parse_error,
            "single_query_stems": _stems(s_docs),
            "nq_stems": _stems(nq_union_docs),
            "rrf_stems": _stems(rrf_docs),
            "combined_stems": _stems(combined_docs),
            "combined_hit": combined_hit,
            "combined_queries": combined_queries,
            "single_docs": [_doc_detail(d, s, "1q") for d, s in s_scored],
            "nq_docs": [_doc_detail(d, 0.0, "Nq") for d in nq_union_docs],
            "rrf_docs": [_doc_detail(d, s, "RRF") for d, s in rrf_scored],
            "combined_docs": [_doc_detail(d, s, "1q+Nq") for d, s in combined_scored],
            "single_latency_ms": single_ms,
            "multi_latency_ms": multi_ms,
            "k": k,
            "model": settings.llm_chat_model,
        })

    _write_run_jsonl(run_file, records)

    # ── summary ──
    n = max(1, len(cases))
    console.print()
    summary = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    summary.add_column(style="dim", width=20)
    summary.add_column(justify="right", width=8)
    summary.add_column(justify="right", width=8)
    summary.add_column(justify="right", width=8)
    summary.add_row(
        f"hit-rate@{k}",
        "[dim]1q[/dim]",
        f"[white]{single_hits}/{len(cases)}[/white]",
        f"[white]{single_hits / n:.0%}[/white]",
    )
    summary.add_row(
        "",
        "[yellow]Nq[/yellow]",
        f"[yellow]{nq_hits}/{len(cases)}[/yellow]",
        f"[yellow]{nq_hits / n:.0%}[/yellow]",
    )
    summary.add_row(
        "",
        "[cyan]RRF[/cyan]",
        f"[cyan]{rrf_hits}/{len(cases)}[/cyan]",
        f"[cyan]{rrf_hits / n:.0%}[/cyan]",
    )
    summary.add_row(
        "",
        "[green]1q+Nq[/green]",
        f"[green]{combined_hits}/{len(cases)}[/green]",
        f"[green]{combined_hits / n:.0%}[/green]",
    )
    delta_nq = (nq_hits - single_hits) / n
    delta_rrf = (rrf_hits - single_hits) / n
    delta_combined = (combined_hits - single_hits) / n
    nq_style = "green" if delta_nq > 0 else ("red" if delta_nq < 0 else "dim")
    rrf_style = "green" if delta_rrf > 0 else ("red" if delta_rrf < 0 else "dim")
    combined_style = "green" if delta_combined > 0 else ("red" if delta_combined < 0 else "dim")
    summary.add_row("delta Nq − 1q", "", "", f"[{nq_style}]{delta_nq:+.0%}[/{nq_style}]")
    summary.add_row("delta RRF − 1q", "", "", f"[{rrf_style}]{delta_rrf:+.0%}[/{rrf_style}]")
    summary.add_row("delta 1q+Nq − 1q", "", "", f"[{combined_style}]{delta_combined:+.0%}[/{combined_style}]")
    parse_err_style = "bold red" if parse_errors else "dim"
    summary.add_row(
        "erros de parse",
        "",
        f"[{parse_err_style}]{parse_errors}/{len(cases)}[/{parse_err_style}]",
        f"[{parse_err_style}]{parse_errors / n:.0%}[/{parse_err_style}]",
    )
    console.print(summary)
    console.print(f"[dim]Run salvo em:[/dim] {run_file}")

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--eval-file", default=None,
        help="JSONL de perguntas curadas (sobrescreve --with-history; default: dataset sem histórico).",
    )
    p.add_argument(
        "--with-history", action="store_true",
        help=f"Usa o dataset com histórico de conversa ({DEFAULT_EVAL_FILE_HISTORY.name}) em vez do padrão.",
    )
    p.add_argument("--k", type=int, default=None, help="Top-k avaliado (default: rag_retrieve_final_k).")
    p.add_argument("--env-file", default=str(DEFAULT_ENV_FILE),
                   help=f"Arquivo .env a carregar (default: {DEFAULT_ENV_FILE}).")
    p.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR),
                   help=f"Diretório onde o JSONL da execução é gravado (default: {DEFAULT_RUNS_DIR}).")
    p.add_argument(
        "--docs", nargs="?", const=6, default=None, type=int, metavar="N",
        help="Exibe top N chunks do caminho N-query+RRF, por rrf_score (sem valor → N=6).",
    )
    p.add_argument(
        "--docs-single", nargs="?", const=6, default=None, type=int, metavar="N",
        help="Exibe top N chunks do caminho 1-query, por dist_score (sem valor → N=6).",
    )
    p.add_argument(
        "--docs-nq", nargs="?", const=6, default=None, type=int, metavar="N",
        help="Exibe top N chunks do caminho Nq (union das N queries, por dist_score, sem valor → N=6).",
    )
    p.add_argument(
        "--docs-combined", nargs="?", const=6, default=None, type=int, metavar="N",
        help="Exibe top N chunks do caminho 1q+Nq (pergunta + queries CoT via RRF, sem valor → N=6).",
    )
    return p.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
