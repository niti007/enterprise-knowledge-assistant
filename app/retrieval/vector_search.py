"""
retrieval/vector_search.py
==========================
Query ChromaDB for top-k similar chunks given a user query.
Embeds the query with the same model used during indexing.

Usage:
    from app.retrieval.vector_search import VectorSearcher
    searcher = VectorSearcher()
    results = searcher.search("Who owns the Payment-Service?", k=5)
    # results = [{"text": ..., "metadata": ..., "score": ...}, ...]
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.retrieval.embeddings import get_chroma_collection

settings = get_settings()


class VectorSearcher:
    """Thread-safe searcher that lazily initialises the ChromaDB collection
    (bound to the same embedding function used during indexing)."""

    def __init__(self) -> None:
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            try:
                self._collection = get_chroma_collection()
            except Exception:
                raise RuntimeError(
                    f"ChromaDB collection '{settings.chroma_collection_name}' not found. "
                    "Run: python -m app.ingestion.chunker"
                )
        return self._collection

    def search(
        self,
        query: str,
        k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search ChromaDB for top-k chunks matching query.

        Parameters
        ----------
        query  : Natural-language query string.
        k      : Number of results (default: settings.retrieval_top_k).
        filters: Optional Chroma `where` filter dict, e.g. {"doc_type": "policy"}.

        Returns
        -------
        List of dicts: [{text, metadata, score, rank}, ...]
        sorted by relevance (best first).
        """
        top_k = k or settings.retrieval_top_k
        collection = self._get_collection()

        if collection.count() == 0:
            raise RuntimeError(
                "ChromaDB collection is empty. "
                "Run: python -m app.ingestion.chunker"
            )

        # Pass raw text — the collection's bound embedding_function embeds the
        # query the same way it embedded the documents at index time.
        kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results": min(top_k, collection.count()),
            "include": ["documents", "metadatas", "distances"],
        }
        if filters:
            kwargs["where"] = filters

        results = collection.query(**kwargs)

        # Flatten Chroma's nested lists
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        output: list[dict[str, Any]] = []
        for rank, (text, meta, dist) in enumerate(zip(docs, metas, distances)):
            # Cosine distance → similarity score (0..1, higher = better)
            score = 1.0 - dist
            output.append({
                "text": text,
                "metadata": meta,
                "score": round(score, 4),
                "rank": rank + 1,
            })

        return output


@lru_cache(maxsize=1)
def get_searcher() -> VectorSearcher:
    """Module-level cached searcher singleton."""
    return VectorSearcher()
