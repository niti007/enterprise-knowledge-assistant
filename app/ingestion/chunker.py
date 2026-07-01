"""
ingestion/chunker.py
====================
1. Recursively chunk documents (~500 tokens, 50 overlap).
2. Embed via the configured embedding provider (local ONNX MiniLM by default,
   or OpenAI embeddings — see app.retrieval.embeddings).
3. Persist to ChromaDB.

Run:
    python -m app.ingestion.chunker
    # or
    python app/ingestion/chunker.py

Requires: OPENAI_API_KEY set in .env (or environment) for chat; embeddings
run locally by default (EMBEDDING_PROVIDER=local).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.ingestion.loader import load_all
from app.retrieval.embeddings import get_chroma_collection

settings = get_settings()

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 chars (good enough for splitting)."""
    return len(text) // 4


def recursive_split(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[str]:
    """
    Recursive character splitter.
    Tries to split on double-newline, then newline, then space, then char.
    """
    separators = ["\n\n", "\n", ". ", " ", ""]

    def _split(text: str, seps: list[str]) -> list[str]:
        if not seps or _estimate_tokens(text) <= chunk_size:
            return [text] if text.strip() else []

        sep = seps[0]
        parts = text.split(sep) if sep else list(text)
        chunks: list[str] = []
        current = ""

        for part in parts:
            candidate = (current + sep + part) if current else part
            if _estimate_tokens(candidate) > chunk_size and current:
                chunks.append(current)
                # start new chunk with overlap
                overlap_text = current[-chunk_overlap * 4:]  # chars ~ tokens
                current = (overlap_text + sep + part).strip() if overlap_text else part
            else:
                current = candidate

        if current.strip():
            chunks.append(current)

        # Recurse on any chunks still too large
        result: list[str] = []
        for chunk in chunks:
            if _estimate_tokens(chunk) > chunk_size:
                result.extend(_split(chunk, seps[1:]))
            else:
                if chunk.strip():
                    result.append(chunk)
        return result

    return _split(text, separators)


def chunk_document(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Split a document into chunks, each carrying the doc's metadata."""
    text = doc["text"]
    meta = doc["metadata"]
    chunks_text = recursive_split(text, settings.chunk_size, settings.chunk_overlap)
    chunks = []
    for i, chunk in enumerate(chunks_text):
        chunk_meta = {**meta, "chunk_index": i, "total_chunks": len(chunks_text)}
        chunks.append({
            "id": f"{meta['source']}_chunk_{i}",
            "text": chunk,
            "metadata": chunk_meta,
        })
    return chunks


# ---------------------------------------------------------------------------
# Embedding + ChromaDB persistence
# ---------------------------------------------------------------------------
# Embedding is handled by Chroma itself via the embedding_function bound to
# the collection (see app.retrieval.embeddings.get_chroma_collection), so
# both indexing here and querying in retrieval/vector_search.py stay
# consistent regardless of EMBEDDING_PROVIDER.

def build_index(raw_dir: Path | None = None) -> None:
    """Load → chunk → embed → persist to ChromaDB."""
    print("[chunker] Loading documents …")
    docs = load_all(raw_dir)

    print("[chunker] Chunking documents …")
    all_chunks: list[dict[str, Any]] = []
    for doc in docs:
        all_chunks.extend(chunk_document(doc))
    print(f"[chunker] Total chunks: {len(all_chunks)}")

    collection = get_chroma_collection()
    existing_count = collection.count()
    if existing_count > 0:
        print(f"[chunker] Collection already has {existing_count} embeddings. Skipping re-index.")
        print("          Delete data/chroma_db/ to force re-index.")
        return

    texts = [c["text"] for c in all_chunks]
    ids = [c["id"] for c in all_chunks]
    metadatas = [c["metadata"] for c in all_chunks]

    print(
        f"[chunker] Embedding + persisting {len(texts)} chunks "
        f"(provider={settings.embedding_provider}) …"
    )
    # Pass raw text and let Chroma's bound embedding_function do the work,
    # so indexing and querying always use the same embedder.
    BATCH = 500
    for start in range(0, len(ids), BATCH):
        collection.add(
            ids=ids[start: start + BATCH],
            documents=texts[start: start + BATCH],
            metadatas=metadatas[start: start + BATCH],
        )
    print(f"[chunker] Done. {collection.count()} vectors in '{settings.chroma_collection_name}'")


if __name__ == "__main__":
    build_index()
