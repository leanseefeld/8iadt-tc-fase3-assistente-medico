#!/usr/bin/env python3
"""Avaliação comparativa: busca de 1 query (pergunta literal) vs N queries + RRF.

Mede hit-rate@k / recall do ``expected_source_stem`` (e, opcionalmente,
``expected_sections``) sobre um conjunto curado de perguntas clínicas, comparando:
  - baseline: ``similarity_search_with_score(pergunta, k)``
  - nova busca: subgrafo especializado (plan_queries → search com fusão RRF)

Como rodar (da raiz do repo, com o venv do backend ativo):

    uv run --project backend python llm/scripts/rag_eval_multiquery.py

    Opções:
      --k 10                    top-k avaliado (default: rag_retrieve_final_k do .env)
      --eval-file path/to.jsonl JSONL alternativo de perguntas
      --env-file path/to/.env   .env alternativo (default: backend/.env)
      --docs [N]                exibe top N chunks do caminho N-query+RRF (default N=6)
      --docs-single [N]         exibe top N chunks do caminho 1-query (default N=6)
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

DEFAULT_EVAL_FILE = REPO_ROOT / "llm" / "data" / "eval" / "rag_questions.jsonl"
DEFAULT_RUNS_DIR = REPO_ROOT / "llm" / "data" / "eval" / "runs"

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
    store, settings: Settings, question: str
) -> tuple[list[Document], list[str], str, str, str | None, list[tuple[Document, float]]]:
    """Retorna (docs, queries, llm_reasoning, raw_llm, error, scored)."""
    plan = await plan_queries_node({"query": question, "reasoning_steps": []}, settings)
    debug = plan.get("multi_query_debug") or {}
    queries = plan.get("search_queries") or [question]
    llm_reasoning = debug.get("reasoning") or ""
    raw_llm = debug.get("raw") or ""
    plan_error = debug.get("error")
    out = search_node({"search_queries": queries, "reasoning_steps": []}, store=store, settings=settings)
    fused: list[Document] = out.get("retrieved_docs") or []
    scored = [(doc, float((doc.metadata or {}).get("rrf_score", 0.0))) for doc in fused]
    return fused, queries, llm_reasoning, raw_llm, plan_error, scored


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
    show_multi: int | None = args.docs
    show_single: int | None = args.docs_single
    store = load_store()
    cases = load_cases(Path(args.eval_file))

    run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    runs_dir = Path(args.runs_dir)
    run_file = runs_dir / f"run_{run_ts}.jsonl"

    single_hits = 0
    multi_hits = 0
    records: list[dict] = []

    console.print()
    console.rule(f"[bold]Avaliando {len(cases)} perguntas  k={k}[/bold]")
    console.print()

    for idx, case in enumerate(cases, start=1):
        question = case["question"]
        expected = case.get("expected_source_stem", "")

        t0 = time.perf_counter()
        s_docs, s_scored = single_query_docs(store, question, k)
        single_ms = round((time.perf_counter() - t0) * 1000, 1)

        t1 = time.perf_counter()
        m_docs, queries, llm_reasoning, raw_llm, plan_error, m_scored = await multi_query_docs(store, settings, question)
        multi_ms = round((time.perf_counter() - t1) * 1000, 1)

        s_hit = _hit(s_docs, expected)
        m_hit = _hit(m_docs, expected)
        single_hits += int(s_hit)
        multi_hits += int(m_hit)

        # ── question header ──
        header = Text()
        header.append(f"{idx:>2}. ", style="bold dim")
        header.append(question, style="bold white")
        console.print(header)

        # ── expected / hit badges ──
        meta_line = Text("    ")
        meta_line.append("esperado ", style="dim")
        meta_line.append(expected or "—", style="bold yellow")
        meta_line.append("  1q ", style="dim")
        meta_line.append_text(_hit_badge(s_hit))
        meta_line.append("  Nq ", style="dim")
        meta_line.append_text(_hit_badge(m_hit))
        meta_line.append(f"  {len(queries)} queries  ", style="dim")
        meta_line.append(f"{multi_ms:.0f}ms", style="dim")
        console.print(meta_line)

        # ── CoT / raw fallback ──
        if llm_reasoning:
            console.print(_reasoning_panel(llm_reasoning), style="dim")
        elif raw_llm:
            available = console.width - 4
            raw_line = raw_llm.replace("\n", " ")
            truncated = raw_line[:available - 1] + "…" if len(raw_line) > available else raw_line
            console.print(f"  [red]{truncated}[/red]")

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

        if show_multi is not None:
            champion_map = _build_champion_map(store, queries)
            console.print(
                f"  [bold cyan]N-query + RRF[/bold cyan]"
                f"[dim]  top {show_multi}  ↑ rrf_score[/dim]"
            )
            console.print(_docs_table(m_scored, show_multi, "rrf_score", champion_map, expected))

        console.rule(style="dim")

        records.append({
            "run_ts": run_ts,
            "idx": idx,
            "question": question,
            "expected_source_stem": expected,
            "single_query_hit": s_hit,
            "multi_query_hit": m_hit,
            "generated_queries": queries,
            "llm_reasoning": llm_reasoning,
            "raw_llm": raw_llm,
            "plan_error": plan_error,
            "single_query_stems": _stems(s_docs),
            "multi_query_stems": _stems(m_docs),
            "single_docs": [_doc_detail(d, s, "1q") for d, s in s_scored],
            "multi_docs": [_doc_detail(d, s, "Nq") for d, s in m_scored],
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
        "[dim]1-query[/dim]",
        f"[white]{single_hits}/{len(cases)}[/white]",
        f"[white]{single_hits / n:.0%}[/white]",
    )
    summary.add_row(
        "",
        "[cyan]N-query[/cyan]",
        f"[cyan]{multi_hits}/{len(cases)}[/cyan]",
        f"[cyan]{multi_hits / n:.0%}[/cyan]",
    )
    delta = (multi_hits - single_hits) / n
    delta_style = "green" if delta > 0 else ("red" if delta < 0 else "dim")
    summary.add_row("delta (N − 1)", "", "", f"[{delta_style}]{delta:+.0%}[/{delta_style}]")
    console.print(summary)
    console.print(f"[dim]Run salvo em:[/dim] {run_file}")

    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--eval-file", default=str(DEFAULT_EVAL_FILE), help="JSONL de perguntas curadas.")
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
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
