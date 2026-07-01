"""
retrieval/embeddings.py
========================
Shared helper for getting the ChromaDB collection + embedding function so
that indexing (ingestion/chunker.py) and querying (retrieval/vector_search.py)
always agree on how text is embedded.

Gated on settings.embedding_provider:
    "local"  -> ChromaDB's built-in ONNXMiniLM_L6_V2 (no API key, no torch).
    anything else (default "openai") -> OpenAI embeddings via the configured
                                         OpenAI-compatible client.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def get_embedding_function():
    """
    Return a Chroma-compatible embedding function based on EMBEDDING_PROVIDER.

    - "local": chromadb.utils.embedding_functions.ONNXMiniLM_L6_V2()
      Downloads a small ONNX model once on first use; runs fully locally.
    - else: OpenAI-compatible embedding function (e.g. text-embedding-3-small).
      Note: OpenRouter does NOT support embeddings, so this path requires a
      real OpenAI API key/base URL if ever re-enabled.
    """
    from chromadb.utils import embedding_functions

    if settings.embedding_provider == "local":
        return embedding_functions.ONNXMiniLM_L6_V2()
    else:
        kwargs: dict[str, Any] = {
            "api_key": settings.openai_api_key,
            "model_name": settings.embedding_model,
        }
        if settings.openai_base_url:
            kwargs["api_base"] = settings.openai_base_url
        return embedding_functions.OpenAIEmbeddingFunction(**kwargs)


def get_chroma_collection():
    """Return (or create) the persistent ChromaDB collection, bound to the
    embedding function selected by EMBEDDING_PROVIDER. Used by both the
    ingestion chunker and the vector searcher so embeddings stay consistent.
    """
    import chromadb  # type: ignore

    client = chromadb.PersistentClient(path=str(settings.chroma_persist_path))
    collection = client.get_or_create_collection(
        name=settings.chroma_collection_name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=get_embedding_function(),
    )
    return collection
