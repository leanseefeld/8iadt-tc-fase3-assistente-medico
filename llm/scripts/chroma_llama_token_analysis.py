"""
Análise de tokens Llama 3.2 por PCDT (Chroma) para decisões de contexto RAG.

Conta tokens com o vocabulário do modelo de geração (ex.: Llama 3.2 3B via mlx-lm),
não com o embedder (nomic-embed-text). Inclui cache em memória por runtime Python.

Uso em notebook:
    from chroma_llama_token_analysis import ChromaLlamaTokenAnalyzer, display_context_report

Uso CLI:
    cd llm && python scripts/chroma_llama_token_analysis.py --max-documents 20
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
_LLM_ROOT = _SCRIPT_DIR.parent
_REPO_ROOT = _LLM_ROOT.parent

sys.path.insert(0, str(_LLM_ROOT / "src"))

from pcdt_ingest.pipeline_config import get_config  # noqa: E402
from pcdt_ingest.paths import vectorstore_chroma_dir  # noqa: E402

# Repositório HF com tokenizer Llama 3.2 (mesmo vocabulário que Ollama ``llama3.2:3b``).
DEFAULT_HF_TOKENIZER_REPO = "unsloth/llama-3.2-3b-instruct-unsloth-bnb-4bit"
DEFAULT_CONTEXT_WINDOW = 128_000
DEFAULT_RETRIEVAL_K = 6

# Teto de referência para gráficos e tabela de k (orçamentos até 200k).
MAX_REFERENCE_CONTEXT = 262_144

# Limite padrão do eixo k no gráfico da §10 (None = todos os chunks do escopo).
DEFAULT_MAX_K_CHART = 500

# Cabeçalho ``[n] PCDT stem=…`` em ``format_context_block`` (estimativa em tokens).
HEADER_TOKENS_PER_CHUNK = 55

# Referências comuns de janela (linhas no gráfico de acumulado).
STANDARD_CONTEXT_BUDGETS: tuple[int, ...] = (
    256,
    512,
    1_024,
    2_048,
    4_096,
    8_192,
    16_384,
    32_768,
    65_536,
    131_072,
)

# --- Estimativa de VRAM (Llama 3.2 3B, inferência batch=1) ---


@dataclass(frozen=True)
class LlamaModelVramSpec:
    """Arquitetura usada nas fórmulas de KV cache (valores Llama 3.2 3B)."""

    name: str = "Llama-3.2-3B"
    num_parameters_b: float = 3.21
    num_layers: int = 28
    num_kv_heads: int = 8
    head_dim: int = 128
    # Scratch CUDA: ativações, grafo, tokenizer — ordem de ~0,5–1 GiB no 3B.
    inference_overhead_gb: float = 0.75


@dataclass(frozen=True)
class QuantizationProfile:
    """Perfil de quantização dos pesos do modelo (KV cache mantido em fp16)."""

    id: str
    label: str
    bytes_per_param: float
    kv_cache_bytes_per_element: float = 2.0
    notes: str = ""


DEFAULT_LLAMA_VRAM_SPEC = LlamaModelVramSpec()

# Perfis típicos Ollama / CUDA / MLX (pesos; KV em fp16).
DEFAULT_QUANTIZATION_PROFILES: tuple[QuantizationProfile, ...] = (
    QuantizationProfile(
        "q4_k_m",
        "Q4_K_M (4-bit, Ollama padrão)",
        0.58,
        notes="~bnb 4-bit / GGUF Q4_K_M",
    ),
    QuantizationProfile(
        "q8_0",
        "Q8_0 (8-bit)",
        1.0,
        notes="GGUF Q8",
    ),
    QuantizationProfile(
        "fp16",
        "FP16 (CUDA comum)",
        2.0,
        notes="half precision weights",
    ),
    QuantizationProfile(
        "bf16",
        "BF16",
        2.0,
        notes="Apple Silicon / treino",
    ),
    QuantizationProfile(
        "fp32",
        "FP32 (referência)",
        4.0,
        notes="sem quantização",
    ),
)


def estimate_weight_vram_gb(
    model: LlamaModelVramSpec,
    profile: QuantizationProfile,
) -> float:
    """VRAM dos pesos do modelo."""
    params = model.num_parameters_b * 1_000_000_000
    return params * profile.bytes_per_param / (1024**3)


def estimate_kv_cache_vram_gb(
    context_tokens: int,
    model: LlamaModelVramSpec,
    profile: QuantizationProfile,
) -> float:
    """VRAM do KV cache (cresce linearmente com o contexto)."""
    if context_tokens <= 0:
        return 0.0
    bytes_per_token = (
        2
        * model.num_layers
        * model.num_kv_heads
        * model.head_dim
        * profile.kv_cache_bytes_per_element
    )
    return context_tokens * bytes_per_token / (1024**3)


def estimate_total_vram_gb(
    context_tokens: int,
    model: LlamaModelVramSpec | None = None,
    profile: QuantizationProfile | None = None,
) -> dict[str, float]:
    """Retorna pesos, KV, overhead e total em GiB."""
    m = model or DEFAULT_LLAMA_VRAM_SPEC
    p = profile or DEFAULT_QUANTIZATION_PROFILES[0]
    weights = estimate_weight_vram_gb(m, p)
    kv = estimate_kv_cache_vram_gb(context_tokens, m, p)
    overhead = m.inference_overhead_gb
    total = weights + kv + overhead
    return {
        "weight_vram_gb": round(weights, 2),
        "kv_cache_vram_gb": round(kv, 2),
        "overhead_gb": round(overhead, 2),
        "total_vram_gb": round(total, 2),
    }


def build_vram_context_profile(
    context_lengths: Iterable[int] | None = None,
    *,
    model: LlamaModelVramSpec | None = None,
    quant_profiles: Iterable[QuantizationProfile] | None = None,
) -> pd.DataFrame:
    """
    Tabela longa: uma linha por (contexto, quantização) com VRAM estimada.
    """
    m = model or DEFAULT_LLAMA_VRAM_SPEC
    quants = list(quant_profiles or DEFAULT_QUANTIZATION_PROFILES)
    lengths = sorted({int(x) for x in (context_lengths or STANDARD_CONTEXT_BUDGETS)})

    rows: list[dict[str, Any]] = []
    for ctx in lengths:
        for q in quants:
            parts = estimate_total_vram_gb(ctx, m, q)
            rows.append(
                {
                    "context_tokens": ctx,
                    "quantization": q.id,
                    "quant_label": q.label,
                    "bytes_per_param": q.bytes_per_param,
                    **parts,
                }
            )
    return pd.DataFrame(rows)


def vram_pivot_table(
    vram_df: pd.DataFrame,
    *,
    value_col: str = "total_vram_gb",
) -> pd.DataFrame:
    """Pivot: linhas = contexto, colunas = quantização."""
    if vram_df.empty:
        return vram_df
    return (
        vram_df.pivot(index="context_tokens", columns="quant_label", values=value_col)
        .sort_index()
        .round(2)
    )


def plot_vram_by_context_length(
    vram_df: pd.DataFrame,
    *,
    context_window: int | None = None,
    doc_budget: int | None = None,
    max_context_plot: int | None = None,
    highlight_contexts: Iterable[int] | None = None,
    ax=None,
):
    """
    VRAM total (GiB) vs tamanho do contexto; uma curva por quantização.

    Eixo X = tokens de contexto; eixo Y = VRAM estimada (pesos + KV fp16 + overhead).
    """
    import matplotlib.pyplot as plt

    if vram_df.empty:
        raise ValueError("vram_df vazio — chame build_vram_context_profile antes.")

    cap = max_context_plot if max_context_plot is not None else MAX_REFERENCE_CONTEXT
    plot_df = vram_df[vram_df["context_tokens"] <= cap].copy()

    if ax is None:
        fig, ax = plt.subplots(figsize=(12, 6.5))
    else:
        fig = ax.figure

    cmap = plt.colormaps["tab10"]
    for i, (label, grp) in enumerate(plot_df.groupby("quant_label", sort=False)):
        grp = grp.sort_values("context_tokens")
        ax.plot(
            grp["context_tokens"],
            grp["total_vram_gb"],
            marker="o",
            markersize=4,
            linewidth=2,
            color=cmap(i % 10),
            label=label,
        )

    highlights = set(highlight_contexts or ())
    if context_window is not None:
        highlights.add(int(context_window))
    if doc_budget is not None:
        highlights.add(int(doc_budget))

    for ctx in sorted(highlights):
        if ctx > cap:
            continue
        ax.axvline(ctx, color="dimgray", linestyle=":", alpha=0.5, linewidth=1)
        ax.text(
            ctx,
            0.98,
            f" {ctx // 1000}k" if ctx >= 1000 else f" {ctx}",
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="top",
            fontsize=8,
            color="dimgray",
            rotation=90,
        )

    if context_window is not None and context_window <= cap:
        ax.axvline(
            context_window,
            color="crimson",
            linestyle="-",
            linewidth=1.8,
            label=f"CONTEXT_WINDOW ({context_window:,})",
        )
    if doc_budget is not None and doc_budget != context_window and doc_budget <= cap:
        ax.axvline(
            doc_budget,
            color="darkorange",
            linestyle="-.",
            linewidth=1.8,
            label=f"DOC_BUDGET ({doc_budget:,})",
        )

    ax.set_xlabel(
        "Tamanho do contexto (tokens no prompt)\n"
        "→ mais contexto = mais KV cache na VRAM",
        fontsize=11,
    )
    ax.set_ylabel(
        "VRAM estimada (GiB)\n"
        "pesos quantizados + KV cache (fp16) + overhead fixo",
        fontsize=11,
    )
    ax.set_title(
        f"VRAM vs contexto — {DEFAULT_LLAMA_VRAM_SPEC.name} (inferência batch=1)",
        fontsize=13,
        pad=12,
    )
    fig.text(
        0.5,
        0.02,
        "Estimativa heurística; Ollama/CUDA/MLX reais variam ±10–20%. KV em fp16; pesos conforme quantização.",
        ha="center",
        fontsize=9,
        color="dimgray",
    )
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=7, framealpha=0.95)
    plt.tight_layout(rect=[0, 0.04, 1, 1])
    return ax


# Padrões HF para baixar só tokenizer (sem pesos do modelo).
_TOKENIZER_ALLOW_PATTERNS = (
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "tokenizer.model",
    "*.jinja",
)


@dataclass
class _RuntimeCache:
    """Cache por processo; sobrevive a re-execuções de célula no mesmo kernel Jupyter."""

    hf_repo: str | None = None
    tokenizer: Any = None
    chunk_tokens: dict[str, int] = field(default_factory=dict)
    doc_rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    max_documents_seen: int = 0
    chroma_fingerprint: str | None = None


# Uma instância global — notebooks reutilizam entre células.
_RUNTIME = _RuntimeCache()


def _chars_token_estimate(text: str, chars_per_token: int = 4) -> int:
    return max(1, len(text) // chars_per_token) if text else 0


def load_llama_tokenizer(
    hf_repo: str = DEFAULT_HF_TOKENIZER_REPO,
    *,
    backend: str = "mlx",
) -> tuple[Any, Callable[[str], int], str]:
    """
    Carrega tokenizador Llama 3.2 sem pesos do modelo.

    ``backend='mlx'``: ``mlx_lm.utils.load_tokenizer`` + snapshot HF só de tokenizer.
    ``backend='transformers'``: ``AutoTokenizer`` (mesmo vocabulário, menos deps MLX).
    """
    if backend == "mlx":
        try:
            from huggingface_hub import snapshot_download
            from mlx_lm.utils import load_tokenizer
        except ImportError as exc:
            raise ImportError(
                "backend='mlx' requer: pip install mlx-lm huggingface_hub"
            ) from exc

        local_path = snapshot_download(
            hf_repo,
            allow_patterns=list(_TOKENIZER_ALLOW_PATTERNS),
        )
        tokenizer = load_tokenizer(local_path)

        def count(text: str) -> int:
            return len(tokenizer.encode(text or ""))

        label = f"mlx-lm ({hf_repo})"
        return tokenizer, count, label

    if backend == "transformers":
        try:
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise ImportError(
                "backend='transformers' requer: pip install transformers"
            ) from exc

        tokenizer = AutoTokenizer.from_pretrained(hf_repo, use_fast=True)

        def count(text: str) -> int:
            return len(tokenizer.encode(text or "", add_special_tokens=False))

        label = f"transformers ({hf_repo})"
        return tokenizer, count, label

    raise ValueError(f"backend desconhecido: {backend!r}")


def _chroma_fingerprint(chroma_dir: Path, collection: str) -> str:
    import chromadb

    client = chromadb.PersistentClient(path=str(chroma_dir))
    col = client.get_collection(collection)
    return f"{chroma_dir.resolve()}|{collection}|{col.count()}"


def _load_chroma_chunks(chroma_dir: Path, collection: str) -> list[dict[str, Any]]:
    import chromadb

    client = chromadb.PersistentClient(path=str(chroma_dir))
    col = client.get_collection(collection)
    result = col.get(include=["documents", "metadatas"])
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    rows: list[dict[str, Any]] = []
    for chunk_id, text, meta in zip(ids, documents, metadatas):
        meta = meta or {}
        rows.append(
            {
                "chunk_id": chunk_id,
                "text": text or "",
                "source_stem": meta.get("source_stem", "<sem source_stem>"),
                "page_start": meta.get("page_start"),
                "page_end": meta.get("page_end"),
                "section": meta.get("section"),
            }
        )
    return rows


def _aggregate_doc_row(
    stem: str,
    chunk_token_list: list[int],
    *,
    total_chars: int,
    retrieval_k: int,
    context_window: int,
    chars_per_token: int,
) -> dict[str, Any]:
    n = len(chunk_token_list)
    total = sum(chunk_token_list)
    mx = max(chunk_token_list) if chunk_token_list else 0
    mn = min(chunk_token_list) if chunk_token_list else 0
    avg = total / n if n else 0.0
    sorted_desc = sorted(chunk_token_list, reverse=True)
    sorted_asc = sorted(chunk_token_list)
    k = min(retrieval_k, n) if n else 0
    sum_top_k_largest = sum(sorted_desc[:k]) if k else 0
    sum_top_k_smallest = sum(sorted_asc[:k]) if k else 0
    # Cabeçalho [n] PCDT stem=... no format_context_block (~40–60 tokens por chunk).
    header_per_chunk = HEADER_TOKENS_PER_CHUNK
    retrieval_block_tokens = sum_top_k_largest + k * header_per_chunk

    row: dict[str, Any] = {
        "source_stem": stem,
        "chunks": n,
        "total_tokens": total,
        "max_chunk_tokens": mx,
        "min_chunk_tokens": mn,
        "avg_chunk_tokens": round(avg, 1),
        "p95_chunk_tokens": int(pd.Series(chunk_token_list).quantile(0.95)) if n else 0,
        f"sum_top_{retrieval_k}_largest": sum_top_k_largest,
        f"sum_top_{retrieval_k}_smallest": sum_top_k_smallest,
        "retrieval_block_est": retrieval_block_tokens,
        "full_doc_pct_context": round(100.0 * total / context_window, 2) if context_window else 0.0,
        "retrieval_block_pct_context": round(
            100.0 * retrieval_block_tokens / context_window, 2
        )
        if context_window
        else 0.0,
        "fits_in_context_window": total <= context_window,
        "fits_retrieval_in_context_window": retrieval_block_tokens <= context_window,
        "fits_full_doc_8k": total <= 8_000,
        "fits_full_doc_16k": total <= 16_000,
        "fits_full_doc_32k": total <= 32_000,
        "fits_retrieval_k_8k": retrieval_block_tokens <= 8_000,
        "fits_retrieval_k_16k": retrieval_block_tokens <= 16_000,
        "fits_retrieval_k_32k": retrieval_block_tokens <= 32_000,
        "chars_estimate_total": _chars_token_estimate(
            " " * total_chars, chars_per_token
        ),
    }
    for k_val in (6, 10, 15, 20):
        kk = min(k_val, n) if n else 0
        row[f"sum_top_{k_val}_largest"] = sum(sorted_desc[:kk]) if kk else 0
    return row


@dataclass
class ChromaLlamaTokenAnalyzer:
    """Analisa tokens por PCDT (source_stem) com cache incremental."""

    chroma_dir: Path | None = None
    collection: str | None = None
    hf_repo: str = DEFAULT_HF_TOKENIZER_REPO
    tokenizer_backend: str = "mlx"
    retrieval_k: int = DEFAULT_RETRIEVAL_K
    context_window: int = DEFAULT_CONTEXT_WINDOW
    chars_per_token: int = 4
    _cache: _RuntimeCache = field(default_factory=lambda: _RUNTIME)

    def __post_init__(self) -> None:
        if self.chroma_dir is None:
            self.chroma_dir = vectorstore_chroma_dir()
        if self.collection is None:
            self.collection = str(get_config("CHROMA_COLLECTION_PCDT", "pcdt"))

    def ensure_tokenizer(self) -> str:
        """Carrega tokenizador uma vez; retorna rótulo do backend."""
        if self._cache.tokenizer is not None and self._cache.hf_repo == self.hf_repo:
            return getattr(self._cache, "_tokenizer_label", self.hf_repo)

        _tok, count_fn, label = load_llama_tokenizer(
            self.hf_repo, backend=self.tokenizer_backend
        )
        self._cache.tokenizer = count_fn
        self._cache.hf_repo = self.hf_repo
        self._cache._tokenizer_label = label  # type: ignore[attr-defined]
        return label

    def _count_tokens(self, text: str) -> int:
        self.ensure_tokenizer()
        assert self._cache.tokenizer is not None
        return int(self._cache.tokenizer(text))

    def _ensure_chroma_loaded(self) -> list[dict[str, Any]]:
        fp = _chroma_fingerprint(self.chroma_dir, self.collection)  # type: ignore[arg-type]
        if self._cache.chroma_fingerprint != fp:
            self._cache.chunk_tokens.clear()
            self._cache.doc_rows.clear()
            self._cache.max_documents_seen = 0
            self._cache.chroma_fingerprint = fp
        if not hasattr(self, "_chunks_by_stem"):
            chunks = _load_chroma_chunks(self.chroma_dir, self.collection)  # type: ignore[arg-type]
            by_stem: dict[str, list[dict[str, Any]]] = {}
            for row in chunks:
                by_stem.setdefault(row["source_stem"], []).append(row)
            self._chunks_by_stem = by_stem
            self._stem_order = sorted(by_stem.keys())
        return self._stem_order  # type: ignore[attr-defined]

    def compute_dataframe(
        self,
        max_documents: int | None = None,
        *,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        Retorna estatísticas por PCDT.

        ``max_documents``: limita quantos ``source_stem`` processar (ordem alfabética).
        Cache: reexecutar com o mesmo ou menor limite não recalcula; limite maior
        só processa stems novos.
        """
        if force_refresh:
            self._cache.doc_rows.clear()
            self._cache.chunk_tokens.clear()
            self._cache.max_documents_seen = 0

        self._ensure_chroma_loaded()
        stems = self._stem_order[: max_documents] if max_documents else self._stem_order
        limit = len(stems)

        if limit > self._cache.max_documents_seen:
            new_stems = stems[self._cache.max_documents_seen :]
            for stem in new_stems:
                if stem in self._cache.doc_rows:
                    continue
                chunk_rows = self._chunks_by_stem[stem]
                token_counts: list[int] = []
                total_chars = 0
                for row in chunk_rows:
                    cid = row["chunk_id"]
                    text = row["text"]
                    total_chars += len(text)
                    if cid not in self._cache.chunk_tokens:
                        self._cache.chunk_tokens[cid] = self._count_tokens(text)
                    token_counts.append(self._cache.chunk_tokens[cid])
                self._cache.doc_rows[stem] = _aggregate_doc_row(
                    stem,
                    token_counts,
                    total_chars=total_chars,
                    retrieval_k=self.retrieval_k,
                    context_window=self.context_window,
                    chars_per_token=self.chars_per_token,
                )
            self._cache.max_documents_seen = limit

        rows = [self._cache.doc_rows[s] for s in stems if s in self._cache.doc_rows]
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        return df.sort_values("total_tokens", ascending=False).reset_index(drop=True)

    def compute_chunks_dataframe(
        self,
        max_documents: int | None = None,
        *,
        min_llama_tokens: int = 0,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        Uma linha por chunk no escopo de ``max_documents``.

        Reutiliza o cache de ``compute_dataframe``. ``min_llama_tokens`` filtra
        chunks com contagem **estritamente maior** que o limiar quando > 0.
        """
        self.compute_dataframe(
            max_documents=max_documents, force_refresh=force_refresh
        )
        self._ensure_chroma_loaded()
        stems = self._stem_order[: max_documents] if max_documents else self._stem_order
        rows: list[dict[str, Any]] = []
        for stem in stems:
            for chunk in self._chunks_by_stem.get(stem, []):
                cid = chunk["chunk_id"]
                text = chunk["text"]
                if cid not in self._cache.chunk_tokens:
                    self._cache.chunk_tokens[cid] = self._count_tokens(text)
                n = int(self._cache.chunk_tokens[cid])
                if min_llama_tokens > 0 and n <= min_llama_tokens:
                    continue
                preview = text if len(text) <= 160 else text[:160] + "…"
                rows.append(
                    {
                        "chunk_id": cid,
                        "source_stem": stem,
                        "llama_tokens": n,
                        "chars": len(text),
                        "page_start": chunk.get("page_start"),
                        "page_end": chunk.get("page_end"),
                        "section": chunk.get("section"),
                        "text_preview": preview,
                    }
                )
        out = pd.DataFrame(rows)
        if out.empty:
            return out
        return out.sort_values("llama_tokens", ascending=False).reset_index(drop=True)

    def estimate_global_retrieval_block(
        self,
        max_documents: int | None = None,
        *,
        retrieval_k: int | None = None,
        context_window: int | None = None,
    ) -> dict[str, Any]:
        """
        Cenário **global** (como o backend): os ``k`` maiores chunks de todo o
        escopo (todos os PCDTs em ``max_documents``), não k por PCDT.

        Proxy pessimista de tamanho para um turno com ``similarity_search(k=k)``:
        “e se os k trechos retornados fossem os k maiores da coleção (no escopo)?”.
        """
        k = retrieval_k if retrieval_k is not None else self.retrieval_k
        window = context_window if context_window is not None else self.context_window
        chunks_df = self.compute_chunks_dataframe(max_documents=max_documents)
        if chunks_df.empty:
            return {
                "retrieval_k": k,
                "global_retrieval_block_est": 0,
                "pct_context_window": 0.0,
                "context_window": window,
                "top_chunks": chunks_df,
            }

        top = chunks_df.nlargest(min(k, len(chunks_df)), "llama_tokens")
        kk = len(top)
        body = int(top["llama_tokens"].sum())
        headers = kk * HEADER_TOKENS_PER_CHUNK
        total = body + headers
        pct = 100.0 * total / window if window else 0.0

        return {
            "retrieval_k": k,
            "chunks_in_block": kk,
            "sum_body_tokens": body,
            "sum_header_tokens": headers,
            "global_retrieval_block_est": total,
            "pct_context_window": round(pct, 2),
            "context_window": window,
            "scope_max_documents": max_documents,
            "scope_pcdts": int(chunks_df["source_stem"].nunique()),
            "scope_chunks": len(chunks_df),
            "top_chunks": top.reset_index(drop=True),
        }

    def estimate_max_largest_chunks_in_context(
        self,
        max_documents: int | None = None,
        *,
        context_window: int | None = None,
        prompt_reserve_tokens: int = 0,
    ) -> dict[str, Any]:
        """
        Quantos dos **maiores** chunks (por tokens Llama) cabem na janela.

        Percorre chunks do maior para o menor e acumula ``tokens + cabeçalho``
        até estourar ``context_window - prompt_reserve_tokens``.
        """
        window = context_window if context_window is not None else self.context_window
        budget = max(0, window - prompt_reserve_tokens)
        chunks_df = self.compute_chunks_dataframe(max_documents=max_documents)
        if chunks_df.empty or budget <= 0:
            return {
                "max_chunks_fit": 0,
                "block_tokens": 0,
                "pct_context_window": 0.0,
                "context_window": window,
                "prompt_reserve_tokens": prompt_reserve_tokens,
                "budget_for_pcdt_block": budget,
                "chunks_in_scope": 0,
                "fitted_chunks": chunks_df,
            }

        cumulative = 0
        fitted_rows: list[dict[str, Any]] = []
        for _, row in chunks_df.iterrows():
            cost = int(row["llama_tokens"]) + HEADER_TOKENS_PER_CHUNK
            if cumulative + cost > budget:
                break
            cumulative += cost
            fitted_rows.append(row.to_dict())

        n_fit = len(fitted_rows)
        pct = 100.0 * cumulative / window if window else 0.0
        fitted = pd.DataFrame(fitted_rows) if fitted_rows else chunks_df.iloc[0:0]

        return {
            "max_chunks_fit": n_fit,
            "sum_body_tokens": int(fitted["llama_tokens"].sum()) if n_fit else 0,
            "sum_header_tokens": n_fit * HEADER_TOKENS_PER_CHUNK,
            "block_tokens": cumulative,
            "remaining_tokens": budget - cumulative,
            "pct_context_window": round(pct, 2),
            "pct_of_budget": round(100.0 * cumulative / budget, 2) if budget else 0.0,
            "context_window": window,
            "prompt_reserve_tokens": prompt_reserve_tokens,
            "budget_for_pcdt_block": budget,
            "scope_max_documents": max_documents,
            "scope_pcdts": int(chunks_df["source_stem"].nunique()),
            "chunks_in_scope": len(chunks_df),
            "fitted_chunks": fitted.reset_index(drop=True),
        }

    def cache_summary(self) -> dict[str, Any]:
        return {
            "chunks_tokenized": len(self._cache.chunk_tokens),
            "documents_cached": len(self._cache.doc_rows),
            "max_documents_seen": self._cache.max_documents_seen,
            "hf_repo": self._cache.hf_repo,
            "chroma_fingerprint": self._cache.chroma_fingerprint,
        }

    def build_cumulative_top_chunks_profile(
        self,
        max_documents: int | None = None,
    ) -> pd.DataFrame:
        """
        Para n = 1 … N, soma dos n maiores chunks (global) + n cabeçalhos.

        Ordenação: ``llama_tokens`` decrescente (mesmo proxy da §6/§7).
        """
        chunks_df = self.compute_chunks_dataframe(max_documents=max_documents)
        if chunks_df.empty:
            return pd.DataFrame(
                columns=[
                    "n_chunks",
                    "cumulative_body",
                    "cumulative_headers",
                    "cumulative_total",
                    "pct_context_window",
                ]
            )

        ordered = chunks_df.sort_values("llama_tokens", ascending=False).reset_index(
            drop=True
        )
        n = pd.Series(range(1, len(ordered) + 1), name="n_chunks")
        cumulative_body = ordered["llama_tokens"].cumsum()
        cumulative_headers = n * HEADER_TOKENS_PER_CHUNK
        cumulative_total = cumulative_body + cumulative_headers
        window = self.context_window
        pct = 100.0 * cumulative_total / window if window else 0.0

        return pd.DataFrame(
            {
                "n_chunks": n,
                "cumulative_body": cumulative_body.astype(int),
                "cumulative_headers": cumulative_headers.astype(int),
                "cumulative_total": cumulative_total.astype(int),
                "pct_context_window": pct.round(2),
            }
        )


def max_n_chunks_within_budget(
    profile: pd.DataFrame,
    budget_tokens: int,
) -> int:
    """Maior ``n_chunks`` cuja ``cumulative_total`` ≤ ``budget_tokens``."""
    if profile.empty or budget_tokens <= 0:
        return 0
    fits = profile[profile["cumulative_total"] <= budget_tokens]
    return int(fits["n_chunks"].max()) if not fits.empty else 0


def recommend_k_for_budgets(
    profile: pd.DataFrame,
    budgets: Iterable[int] | None = None,
    *,
    context_window: int | None = None,
    doc_budget: int | None = None,
) -> pd.DataFrame:
    """
    Para cada orçamento de tokens, devolve o maior k (n chunks) que ainda cabe.
    """
    if profile.empty:
        return pd.DataFrame(columns=["budget_tokens", "max_k", "tokens_at_k"])

    labels: list[tuple[str, int]] = []
    for b in budgets or STANDARD_CONTEXT_BUDGETS:
        labels.append((f"{b // 1000}k" if b >= 1000 else str(b), int(b)))
    if context_window is not None:
        labels.append(("CONTEXT_WINDOW", int(context_window)))
    if doc_budget is not None and doc_budget != context_window:
        labels.append(("DOC_BUDGET", int(doc_budget)))

    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for label, budget in labels:
        if budget in seen:
            continue
        seen.add(budget)
        k = max_n_chunks_within_budget(profile, budget)
        tokens_at_k = (
            int(profile.loc[profile["n_chunks"] == k, "cumulative_total"].iloc[0])
            if k
            else 0
        )
        rows.append(
            {
                "budget_label": label,
                "budget_tokens": budget,
                "max_k": k,
                "tokens_at_k": tokens_at_k,
            }
        )
    return pd.DataFrame(rows)


def slice_profile_for_chart(
    profile: pd.DataFrame,
    max_k: int | None,
) -> tuple[pd.DataFrame, bool]:
    """
    Recorta o perfil acumulado para o gráfico (eixo k).

    Retorna ``(perfil_recortado, truncado_no_eixo_k)``.
    ``max_k=None`` mantém todos os pontos.
    """
    if profile.empty or max_k is None:
        return profile, False
    truncated = int(profile["n_chunks"].max()) > max_k
    return profile[profile["n_chunks"] <= max_k].copy(), truncated


def _format_token_tick(value: float, _pos) -> str:
    """Rótulos do eixo Y em milhares de tokens."""
    if value >= 1000:
        return f"{value / 1000:.0f}k" if value % 1000 == 0 else f"{value / 1000:.1f}k"
    return f"{int(value)}"


def plot_cumulative_top_chunks_profile(
    profile: pd.DataFrame,
    *,
    context_window: int,
    doc_budget: int | None = None,
    budgets: Iterable[int] | None = None,
    highlight_k: int | None = None,
    max_k: int | None = DEFAULT_MAX_K_CHART,
    ax=None,
):
    """
    Gráfico de leitura: quanto o prompt cresce ao aumentar k (maiores chunks).

    - **Eixo horizontal:** k = quantos trechos entram no contexto (os k maiores).
    - **Eixo vertical:** tokens Llama do bloco PCDT (texto + cabeçalhos).
    - **Linhas horizontais:** tetos de orçamento; abaixo da linha = ainda cabe.
    - **max_k:** limita o eixo horizontal (padrão 2000); ``None`` = sem limite.
    """
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    if profile.empty:
        raise ValueError("profile vazio — execute build_cumulative_top_chunks_profile antes.")

    full_profile = profile
    profile, truncated_k_axis = slice_profile_for_chart(profile, max_k)

    if ax is None:
        fig, ax = plt.subplots(figsize=(12, 6.5))
    else:
        fig = ax.figure

    x = profile["n_chunks"]
    y = profile["cumulative_total"]
    y_max_curve = int(y.max())
    # Escala e linhas de referência limitadas a 256k (dados acima são truncados no desenho).
    y_cap = min(MAX_REFERENCE_CONTEXT, max(context_window, y_max_curve))
    y_top = min(y_cap * 1.08, MAX_REFERENCE_CONTEXT * 1.05)
    plot_mask = y <= MAX_REFERENCE_CONTEXT
    x_plot = x[plot_mask]
    y_plot = y[plot_mask]
    truncated = bool((~plot_mask).any())

    # Faixa “segura” até DOC_BUDGET (se definido) ou até a janela inteira.
    budget_fill = doc_budget if doc_budget is not None else context_window
    if budget_fill > 0:
        ax.axhspan(0, budget_fill, facecolor="seagreen", alpha=0.07, zorder=0)
        ax.text(
            0.99,
            budget_fill,
            "  área abaixo = ainda cabe",
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="top",
            fontsize=8,
            color="seagreen",
            alpha=0.9,
        )

    ax.plot(
        x_plot,
        y_plot,
        color="#1f77b4",
        linewidth=2.5,
        marker="o",
        markersize=3,
        markevery=max(1, len(x_plot) // 25),
        zorder=4,
        label="Se você retornar k trechos (os k maiores do índice)",
    )
    if truncated and not x_plot.empty:
        ax.plot(
            x_plot.iloc[-1],
            y_plot.iloc[-1],
            marker=">",
            color="#1f77b4",
            markersize=10,
            zorder=5,
        )
        ax.annotate(
            f"truncado em {MAX_REFERENCE_CONTEXT // 1000}k",
            (x_plot.iloc[-1], y_plot.iloc[-1]),
            textcoords="offset points",
            xytext=(8, -16),
            fontsize=8,
            color="#1f77b4",
        )

    ref_budgets = sorted(
        b for b in set(budgets or STANDARD_CONTEXT_BUDGETS) if b <= MAX_REFERENCE_CONTEXT
    )
    visible_budgets = [b for b in ref_budgets if b <= y_top * 1.02]
    if context_window not in visible_budgets:
        visible_budgets.append(context_window)

    for budget in visible_budgets:
        if budget == context_window:
            continue
        ax.axhline(budget, color="gray", linestyle=":", linewidth=1, alpha=0.55, zorder=1)
        k_at = max_n_chunks_within_budget(full_profile, budget)
        label = f"{budget // 1000}k" if budget >= 1000 else str(budget)
        ax.text(
            0.02,
            budget,
            f"  {label} tokens",
            transform=ax.get_yaxis_transform(),
            ha="left",
            va="center",
            fontsize=8,
            color="dimgray",
            clip_on=True,
        )
        if k_at > 0:
            tok = int(
                full_profile.loc[full_profile["n_chunks"] == k_at, "cumulative_total"].iloc[0]
            )
            on_chart = max_k is None or k_at <= max_k
            if on_chart:
                ax.plot(k_at, tok, "o", color="gray", markersize=5, zorder=3)
                ax.annotate(
                    f"k≤{k_at}",
                    (k_at, tok),
                    textcoords="offset points",
                    xytext=(6, -12),
                    fontsize=8,
                    color="dimgray",
                )
            elif max_k is not None:
                ax.annotate(
                    f"k≤{k_at}",
                    (max_k, min(tok, budget)),
                    textcoords="offset points",
                    xytext=(-28, -12),
                    fontsize=8,
                    color="dimgray",
                    ha="right",
                )

    ax.axhline(
        context_window,
        color="crimson",
        linestyle="-",
        linewidth=2,
        zorder=2,
        label=f"Teto do modelo (CONTEXT_WINDOW = {context_window:,})",
    )
    ax.text(
        0.02,
        context_window,
        f"  janela {context_window // 1000}k",
        transform=ax.get_yaxis_transform(),
        ha="left",
        va="bottom",
        fontsize=9,
        color="crimson",
        fontweight="bold",
        clip_on=True,
    )

    if doc_budget is not None and doc_budget != context_window:
        ax.axhline(
            doc_budget,
            color="darkorange",
            linestyle="-",
            linewidth=2,
            zorder=2,
            label=f"Orçamento PCDT (DOC_BUDGET = {doc_budget:,})",
        )
        k_doc = max_n_chunks_within_budget(full_profile, doc_budget)
        if k_doc > 0:
            tok_doc = int(
                full_profile.loc[full_profile["n_chunks"] == k_doc, "cumulative_total"].iloc[
                    0
                ]
            )
            x_doc = k_doc if max_k is None or k_doc <= max_k else max_k
            y_doc = tok_doc if x_doc == k_doc else int(
                profile["cumulative_total"].iloc[-1]
                if not profile.empty
                else tok_doc
            )
            ax.plot(x_doc, y_doc, "D", color="darkorange", markersize=7, zorder=5)
            suffix = "" if x_doc == k_doc else f" (k real {k_doc})"
            ax.annotate(
                f"k recomendado ≤{k_doc}{suffix}",
                (x_doc, y_doc),
                textcoords="offset points",
                xytext=(10, 10),
                fontsize=9,
                color="darkorange",
                fontweight="bold",
            )

    if highlight_k is not None and highlight_k > 0:
        row = full_profile[full_profile["n_chunks"] == highlight_k]
        if not row.empty:
            xt = int(row["n_chunks"].iloc[0])
            yt = int(row["cumulative_total"].iloc[0])
            x_draw = xt if max_k is None or xt <= max_k else max_k
            y_draw = yt if x_draw == xt else (
                int(profile.loc[profile["n_chunks"] == max_k, "cumulative_total"].iloc[0])
                if max_k and not profile.empty and max_k in profile["n_chunks"].values
                else yt
            )
            ax.axvline(x_draw, color="#1f77b4", linestyle="--", alpha=0.35, zorder=2)
            ax.scatter([x_draw], [y_draw], color="crimson", s=90, zorder=6, edgecolors="white")
            pct = 100.0 * yt / context_window if context_window else 0
            off_chart = x_draw != xt
            ax.annotate(
                f"RETRIEVAL_K = {xt}\n{yt:,} tokens ({pct:.0f}% da janela)"
                + ("\n(fora do zoom k)" if off_chart else ""),
                (x_draw, y_draw),
                textcoords="offset points",
                xytext=(12, 14),
                fontsize=9,
                color="crimson",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.85),
            )

    ax.set_xlabel(
        "k — quantos trechos o retrieve traz (eixo horizontal)\n"
        "→ aumentar k adiciona mais chunks ao prompt",
        fontsize=11,
    )
    ax.set_ylabel(
        "Tamanho do bloco PCDT no prompt (tokens Llama)\n"
        "↑ mais tokens = mais contexto consumido",
        fontsize=11,
    )
    ax.set_title(
        "Quanto contexto os k maiores trechos ocupam?",
        fontsize=13,
        pad=12,
    )
    footer = (
        "Leitura: parta da esquerda (k=1). Siga a curva azul para cima; ao cruzar uma linha horizontal, "
        "esse orçamento de tokens foi ultrapassado. Use a tabela acima para o k máximo por teto."
    )
    if truncated_k_axis and max_k is not None:
        footer += f" Eixo k limitado a {max_k:,} (há mais chunks no índice)."
    fig.text(0.5, 0.02, footer, ha="center", fontsize=9, color="dimgray")

    x_hi = int(x_plot.max()) if not x_plot.empty else 1
    x_limit = max_k if max_k is not None else max(x_hi, int(full_profile["n_chunks"].max()))
    ax.set_xlim(0.5, x_limit + 0.5)
    if truncated_k_axis and max_k is not None:
        ax.axvline(max_k, color="dimgray", linestyle="-.", linewidth=1, alpha=0.6)
        ax.text(
            max_k,
            0.02,
            f" k≤{max_k}",
            transform=ax.get_xaxis_transform(),
            ha="right",
            va="bottom",
            fontsize=8,
            color="dimgray",
        )
    ax.set_ylim(0, y_top)
    ax.yaxis.set_major_formatter(FuncFormatter(_format_token_tick))
    ax.grid(True, axis="y", alpha=0.25)
    ax.grid(True, axis="x", alpha=0.12)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.95)

    plt.tight_layout(rect=[0, 0.05, 1, 1])
    return ax


def report_display_columns(df: pd.DataFrame, retrieval_k: int) -> list[str]:
    """Colunas padrão exibidas nas tabelas do relatório resumido."""
    cols = [
        "source_stem",
        "chunks",
        "total_tokens",
        "max_chunk_tokens",
        "avg_chunk_tokens",
        f"sum_top_{retrieval_k}_largest",
        "retrieval_block_est",
        "full_doc_pct_context",
        "retrieval_block_pct_context",
    ]
    return [c for c in cols if c in df.columns]


def context_report_summary(
    df: pd.DataFrame,
    *,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    retrieval_k: int = DEFAULT_RETRIEVAL_K,
) -> dict[str, Any]:
    """Métricas agregadas do escopo analisado (para print ou markdown dinâmico)."""
    if df.empty:
        return {
            "pcdt_count": 0,
            "chunk_count": 0,
            "grand_tokens": 0,
            "context_window": context_window,
            "retrieval_k": retrieval_k,
        }
    return {
        "pcdt_count": len(df),
        "chunk_count": int(df["chunks"].sum()),
        "grand_tokens": int(df["total_tokens"].sum()),
        "context_window": context_window,
        "retrieval_k": retrieval_k,
        "fits_full_doc_count": int(df["fits_in_context_window"].sum())
        if "fits_in_context_window" in df.columns
        else None,
        "fits_retrieval_count": int(df["fits_retrieval_in_context_window"].sum())
        if "fits_retrieval_in_context_window" in df.columns
        else None,
        "heavy_chunk_pcdt_count": int((df["max_chunk_tokens"] > 600).sum()),
    }


def report_top_by_total_tokens(
    df: pd.DataFrame,
    retrieval_k: int,
    *,
    head: int = 15,
) -> pd.DataFrame:
    """PCDTs mais pesados se todos os chunks fossem considerados."""
    cols = report_display_columns(df, retrieval_k)
    return df[cols].head(head)


def report_pcdts_fitting_full_document(
    df: pd.DataFrame,
    retrieval_k: int,
) -> pd.DataFrame:
    """PCDTs com `total_tokens` dentro de `CONTEXT_WINDOW` usado no `df`."""
    if "fits_in_context_window" not in df.columns:
        return df.iloc[0:0]
    cols = report_display_columns(df, retrieval_k)
    return df.loc[df["fits_in_context_window"], cols]


def report_pcdts_fitting_retrieval_block(
    df: pd.DataFrame,
    retrieval_k: int,
) -> pd.DataFrame:
    """PCDTs em que `retrieval_block_est` cabe na janela configurada no `df`."""
    if "fits_retrieval_in_context_window" not in df.columns:
        return df.iloc[0:0]
    cols = report_display_columns(df, retrieval_k)
    return df.loc[df["fits_retrieval_in_context_window"], cols]


def report_pcdts_with_oversized_chunks(
    df: pd.DataFrame,
    *,
    min_max_chunk_tokens: int = 600,
) -> pd.DataFrame:
    """PCDTs com pelo menos um chunk acima do limiar."""
    mask = df["max_chunk_tokens"] > min_max_chunk_tokens
    return df.loc[
        mask,
        ["source_stem", "chunks", "max_chunk_tokens", "avg_chunk_tokens"],
    ].sort_values("max_chunk_tokens", ascending=False)


def report_retrieval_block_pct_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Estatísticas descritivas de `retrieval_block_pct_context`."""
    if "retrieval_block_pct_context" not in df.columns or df.empty:
        return pd.DataFrame()
    return (
        df["retrieval_block_pct_context"]
        .describe(percentiles=[0.5, 0.75, 0.9, 0.95])
        .to_frame("retrieval_block_pct_context")
    )


def display_context_report(
    df: pd.DataFrame,
    *,
    retrieval_k: int = DEFAULT_RETRIEVAL_K,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
) -> None:
    """Atalho CLI: imprime resumo e tabelas (no notebook use as funções ``report_*``)."""
    if df.empty:
        print("DataFrame vazio — verifique Chroma e max_documents.")
        return

    summary = context_report_summary(
        df, context_window=context_window, retrieval_k=retrieval_k
    )
    print(
        f"\n=== Resumo ({summary['pcdt_count']} PCDTs, "
        f"{summary['chunk_count']:,} chunks, {summary['grand_tokens']:,} tokens Llama) ==="
    )
    print(
        f"Janela de contexto: {context_window:,} | k retrieve: {retrieval_k}"
    )

    _show = _notebook_display()
    print("\n--- Top 15 por total_tokens ---")
    _show(report_top_by_total_tokens(df, retrieval_k))

    fit_full = report_pcdts_fitting_full_document(df, retrieval_k)
    print(
        f"\n--- PCDTs inteiros em CONTEXT_WINDOW: {len(fit_full)} / {summary['pcdt_count']} ---"
    )
    if not fit_full.empty:
        _show(fit_full)

    fit_k = report_pcdts_fitting_retrieval_block(df, retrieval_k)
    print(
        f"\n--- k={retrieval_k} por PCDT em CONTEXT_WINDOW: "
        f"{len(fit_k)} / {summary['pcdt_count']} ---"
    )

    heavy = report_pcdts_with_oversized_chunks(df)
    print(f"\n--- PCDTs com chunk > 600 tokens: {len(heavy)} ---")
    if not heavy.empty:
        _show(heavy)

    print("\n--- Distribuição retrieval_block_pct_context ---")
    _show(report_retrieval_block_pct_stats(df))


def _notebook_display():
    try:
        from IPython.display import display as ipy_display

        return ipy_display
    except ImportError:
        return print


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Tokens Llama por PCDT no Chroma.")
    p.add_argument("--chroma-dir", default=str(vectorstore_chroma_dir()))
    p.add_argument("--collection", default=str(get_config("CHROMA_COLLECTION_PCDT", "pcdt")))
    p.add_argument("--max-documents", type=int, default=None)
    p.add_argument("--hf-repo", default=DEFAULT_HF_TOKENIZER_REPO)
    p.add_argument("--backend", choices=["mlx", "transformers"], default="transformers")
    p.add_argument("--retrieval-k", type=int, default=DEFAULT_RETRIEVAL_K)
    p.add_argument("--context-window", type=int, default=DEFAULT_CONTEXT_WINDOW)
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    chroma_path = Path(args.chroma_dir)
    if not chroma_path.exists():
        print(f"ERRO: Chroma não encontrado: {chroma_path}", file=sys.stderr)
        sys.exit(1)

    analyzer = ChromaLlamaTokenAnalyzer(
        chroma_dir=chroma_path,
        collection=args.collection,
        hf_repo=args.hf_repo,
        tokenizer_backend=args.backend,
        retrieval_k=args.retrieval_k,
        context_window=args.context_window,
    )
    label = analyzer.ensure_tokenizer()
    print(f"Tokenizador: {label}")
    df = analyzer.compute_dataframe(max_documents=args.max_documents)
    print(df.to_string(index=False))
    print("\nCache:", analyzer.cache_summary())


if __name__ == "__main__":
    main()
