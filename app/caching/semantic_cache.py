"""
caching/semantic_cache.py
============================
Semantic cache: embed the query with the shared local embedding function,
store {query_embedding, query_text, answer_payload} in fakeredis (in-process,
no real Redis server needed), and on lookup compute cosine similarity against
all cached embeddings — return the cached answer if similarity >= threshold.

fakeredis is used as a drop-in Redis-compatible backend so the same code path
would work against real Redis (just swap the client construction) while
staying dependency-light for this environment.

Usage:
    from app.caching.semantic_cache import SemanticCache, get_semantic_cache
    cache = get_semantic_cache()
    hit = cache.get(query)            # -> dict | None
    cache.set(query, answer_payload)  # answer_payload: JSON-serializable dict
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

_CACHE_KEY_PREFIX = "semcache:"
_INDEX_KEY = "semcache:__index__"  # sorted set / list of all cache keys


def _json_default(obj: Any) -> Any:
    """Best-effort fallback for json.dumps on values like numpy floats that
    aren't natively JSON-serializable, so a stray numpy type never silently
    breaks caching."""
    try:
        import numpy as np  # type: ignore

        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
    except ImportError:
        pass
    return str(obj)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticCache:
    """Embedding-similarity cache backed by fakeredis (in-process)."""

    def __init__(self, threshold: float | None = None, ttl_s: int | None = None) -> None:
        self.threshold = threshold if threshold is not None else settings.semantic_cache_threshold
        self.ttl_s = ttl_s if ttl_s is not None else settings.semantic_cache_ttl_s
        self._redis = None
        self._embed_fn = None

    # ------------------------------------------------------------------
    def _get_redis(self):
        if self._redis is None:
            import fakeredis

            self._redis = fakeredis.FakeStrictRedis(decode_responses=True)
        return self._redis

    def _get_embed_fn(self):
        if self._embed_fn is None:
            from app.retrieval.embeddings import get_embedding_function

            self._embed_fn = get_embedding_function()
        return self._embed_fn

    def _embed(self, text: str) -> list[float]:
        embed_fn = self._get_embed_fn()
        # Chroma embedding functions take a list of texts and return a list of vectors.
        result = embed_fn([text])
        vec = result[0]
        return list(vec)

    # ------------------------------------------------------------------
    def get(self, query: str) -> dict[str, Any] | None:
        """Look up `query` in the cache. Returns the cached payload dict
        (with an added 'cache_similarity' key) on a hit above threshold,
        else None. Never raises — degrades to cache-miss on any error."""
        if not settings.semantic_cache_enabled:
            return None
        try:
            r = self._get_redis()
            keys = r.smembers(_INDEX_KEY)
            if not keys:
                return None

            query_vec = self._embed(query)
            best_score = -1.0
            best_entry: dict[str, Any] | None = None

            now = time.time()
            for key in keys:
                raw = r.get(key)
                if raw is None:
                    r.srem(_INDEX_KEY, key)
                    continue
                entry = json.loads(raw)
                if entry.get("expires_at", float("inf")) < now:
                    r.delete(key)
                    r.srem(_INDEX_KEY, key)
                    continue
                score = _cosine_similarity(query_vec, entry["embedding"])
                if score > best_score:
                    best_score = score
                    best_entry = entry

            if best_entry is not None and best_score >= self.threshold:
                log.info("semantic_cache_hit", similarity=round(best_score, 4), query_preview=query[:80])
                payload = dict(best_entry["payload"])
                payload["cache_hit"] = True
                payload["cache_similarity"] = round(best_score, 4)
                payload["cached_query"] = best_entry["query_text"]
                return payload

            return None
        except Exception as exc:
            log.warning("semantic_cache_get_failed", error=str(exc))
            return None

    def set(self, query: str, payload: dict[str, Any]) -> None:
        """Store `payload` (JSON-serializable) under the embedding of `query`."""
        if not settings.semantic_cache_enabled:
            return
        try:
            r = self._get_redis()
            query_vec = self._embed(query)
            key = f"{_CACHE_KEY_PREFIX}{abs(hash(query))}_{int(time.time() * 1000)}"
            entry = {
                "query_text": query,
                "embedding": query_vec,
                "payload": payload,
                "expires_at": time.time() + self.ttl_s,
            }
            r.set(key, json.dumps(entry, default=_json_default), ex=self.ttl_s)
            r.sadd(_INDEX_KEY, key)
        except Exception as exc:
            log.warning("semantic_cache_set_failed", error=str(exc))

    def clear(self) -> None:
        try:
            r = self._get_redis()
            keys = r.smembers(_INDEX_KEY)
            for key in keys:
                r.delete(key)
            r.delete(_INDEX_KEY)
        except Exception as exc:
            log.warning("semantic_cache_clear_failed", error=str(exc))


_cache: SemanticCache | None = None


def get_semantic_cache() -> SemanticCache:
    global _cache
    if _cache is None:
        _cache = SemanticCache()
    return _cache
