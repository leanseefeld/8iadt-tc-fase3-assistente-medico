"""Reranking opcional com sentence-transformers CrossEncoder."""

from __future__ import annotations

from functools import lru_cache
import logging
from typing import Any

from langchain_core.documents import Document

_logger = logging.getLogger("assistente_medico.rag")


@lru_cache(maxsize=2)
def load_cross_encoder_model(model_name: str) -> Any | None:
    """Carrega CrossEncoder sob demanda; nunca é chamado se a flag estiver desligada."""
    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(model_name)
    except Exception as exc:
        _logger.warning("cross_encoder_unavailable; fallback heuristico. modelo=%s erro=%s", model_name, exc)
        return None


def _doc_summary(doc: Document) -> str:
    meta = dict(doc.metadata or {})
    page_start = meta.get("page_start", "?")
    page_end = meta.get("page_end", "?")
    return (
        f"Diretriz: {meta.get('diretriz') or '-'}\n"
        f"Doença: {meta.get('disease') or '-'}\n"
        f"Seção: {meta.get('section') or meta.get('header_1') or '-'}\n"
        f"Páginas: {page_start}-{page_end}\n"
        f"Trecho: {str(doc.page_content or '').strip()[:1800]}"
    )


def cross_encoder_score_documents(query: str, documents: list[Document], model: Any) -> list[float]:
    pairs = [(query, _doc_summary(doc)) for doc in documents]
    raw_scores = model.predict(pairs)
    return [float(score) for score in raw_scores]


def _normalize_scores(scores: list[float]) -> list[float]:
    if not scores:
        return []
    low = min(scores)
    high = max(scores)
    if high == low:
        return [0.5 for _ in scores]
    return [(score - low) / (high - low) for score in scores]


def apply_cross_encoder_rerank(
    query: str,
    documents: list[Document],
    *,
    model_name: str,
    top_n: int = 15,
    alpha_heuristic: float = 0.70,
    beta_cross_encoder: float = 0.30,
    model: Any | None = None,
) -> list[Document]:
    """Combina score heurístico e CrossEncoder para o top-N intermediário."""
    if not documents:
        return []
    cross_model = model if model is not None else load_cross_encoder_model(model_name)
    if cross_model is None:
        return documents

    head = documents[: max(1, int(top_n))]
    tail = documents[max(1, int(top_n)) :]
    try:
        cross_scores = cross_encoder_score_documents(query, head, cross_model)
    except Exception as exc:
        _logger.warning("cross_encoder_score_failed; fallback heuristico. erro=%s", exc)
        return documents

    norm_cross = _normalize_scores(cross_scores)
    reranked: list[tuple[float, Document]] = []
    for doc, raw_cross, cross_norm in zip(head, cross_scores, norm_cross, strict=False):
        meta = dict(doc.metadata or {})
        heuristic = float(meta.get("final_score", meta.get("heuristic_score", 0.0)) or 0.0)
        combined = (alpha_heuristic * heuristic) + (beta_cross_encoder * cross_norm)
        reasons = list(meta.get("ranking_reasons") or [])
        reasons.append("cross_encoder_rerank")
        meta.update(
            {
                "heuristic_score_before_cross_encoder": round(heuristic, 6),
                "cross_encoder_score": round(float(raw_cross), 6),
                "cross_encoder_score_normalized": round(float(cross_norm), 6),
                "final_score": round(combined, 6),
                "ranking_reasons": reasons,
            }
        )
        reranked.append((combined, Document(page_content=doc.page_content, metadata=meta, id=getattr(doc, "id", None))))

    reranked.sort(key=lambda item: item[0], reverse=True)
    return [doc for _score, doc in reranked] + tail
