"""
retrieval/hybrid.py
=====================
Hybrid retrieval: run vector_search (ChromaDB) + graph_search (Neo4j) in
parallel-ish, merge + dedup the candidates, then re-rank the merged set with
a local sentence-transformers CrossEncoder. Returns the top-N candidates with
scores + sources, ready for the agent / pipeline to cite.

Usage:
    from app.retrieval.hybrid import hybrid_search
    results = hybrid_search("If Payment-Service goes down, who do I contact?", k=8)
    # -> [{"text", "metadata", "score", "rank", "source"}, ...]
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()


@lru_cache(maxsize=1)
def _get_cross_encoder():
    """Lazily load the local cross-encoder reranker. Cached as a singleton
    since loading the model is relatively expensive."""
    from sentence_transformers import CrossEncoder

    log.info("loading_cross_encoder", model=settings.rerank_model)
    return CrossEncoder(settings.rerank_model)


def _dedup_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedup by normalized text content (vector + graph results rarely overlap,
    but vector itself can return near-duplicate chunks across reruns)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for c in candidates:
        key = c["text"].strip().lower()[:300]
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def hybrid_search(
    query: str,
    k: int | None = None,
    vector_k: int | None = None,
    graph_k: int | None = None,
    use_graph: bool = True,
    use_rerank: bool = True,
) -> list[dict[str, Any]]:
    """
    Run vector + graph retrieval, merge, dedup, and cross-encoder rerank.

    Returns
    -------
    List of dicts: [{text, metadata, score, rank, source}], best first.
    `source` is "vector" or "graph". `score` after rerank is the cross-encoder
    relevance score (not directly comparable to the raw vector/graph scores).
    """
    top_n = k or settings.hybrid_top_n
    candidates: list[dict[str, Any]] = []

    # ---- Vector search -----------------------------------------------
    try:
        from app.retrieval.vector_search import get_searcher

        vsearcher = get_searcher()
        vresults = vsearcher.search(query, k=vector_k or settings.retrieval_top_k)
        for r in vresults:
            candidates.append({
                "text": r["text"],
                "metadata": r["metadata"],
                "score": r["score"],
                "source": "vector",
            })
    except Exception as exc:
        log.warning("hybrid_vector_search_failed", error=str(exc))

    # ---- Graph search ---------------------------------------------------
    if use_graph:
        try:
            from app.retrieval.graph_search import get_graph_searcher

            gsearcher = get_graph_searcher()
            gresults = gsearcher.search(query, k=graph_k or settings.retrieval_top_k)
            for r in gresults:
                candidates.append({
                    "text": r["text"],
                    "metadata": r["metadata"],
                    "score": r["score"],
                    "source": "graph",
                })
        except Exception as exc:
            log.warning("hybrid_graph_search_failed", error=str(exc))

    if not candidates:
        return []

    candidates = _dedup_candidates(candidates)

    # ---- Cross-encoder rerank ------------------------------------------
    if use_rerank and len(candidates) > 1:
        try:
            ce = _get_cross_encoder()
            pairs = [(query, c["text"]) for c in candidates]
            ce_scores = ce.predict(pairs)
            for c, s in zip(candidates, ce_scores):
                c["rerank_score"] = float(s)
            candidates.sort(key=lambda c: c["rerank_score"], reverse=True)
            for c in candidates:
                c["score"] = c["rerank_score"]
        except Exception as exc:
            log.warning("rerank_failed_falling_back_to_raw_scores", error=str(exc))
            candidates.sort(key=lambda c: c["score"], reverse=True)
    else:
        candidates.sort(key=lambda c: c["score"], reverse=True)

    top = candidates[:top_n]
    for i, c in enumerate(top):
        c["rank"] = i + 1
        c.pop("rerank_score", None)
        c["score"] = float(c["score"])  # numpy float32 (from cross-encoder) -> native float

    log.info(
        "hybrid_search_done",
        n_candidates=len(candidates),
        n_returned=len(top),
        n_vector=sum(1 for c in candidates if c["source"] == "vector"),
        n_graph=sum(1 for c in candidates if c["source"] == "graph"),
    )
    return top
