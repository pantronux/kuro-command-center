"""Kuro AI V5.5 — Shared embedding cache (P3.3).

Several hot paths embed the same user query redundantly — Mem0 retrieve,
Chroma retrieval, and the new semantic cache. This module exposes a single
``embed_query`` function with an LRU+TTL layer in front of the Gemini embed
API so we pay for each unique query at most once per TTL window.

Design notes:
- Thread-safe via a single ``RLock`` (cache accesses are cheap, lock
  contention is negligible vs. the embedding API latency we're amortizing).
- Pure in-process state; restart clears cache. That's fine because embeddings
  are idempotent — there's no correctness risk, only a cold-start tax.
- Returns ``None`` on any failure so callers can gracefully fall back to
  whatever path they already use for embedding-free behavior.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Final, Optional, Sequence

logger = logging.getLogger(__name__)

_CACHE_MAX: Final[int] = 1024
_CACHE_TTL_S: Final[float] = 300.0
_EMBED_MODEL: Final[str] = "models/gemini-embedding-001"

_cache: dict[str, tuple[float, tuple[float, ...]]] = {}
_cache_lock = threading.RLock()

_embed_client = None
_embed_client_lock = threading.Lock()


def _get_embed_client():
    """Lazy-init Gemini client (kept separate from the response client to
    avoid creating a dependency cycle through langgraph_core)."""
    global _embed_client
    if _embed_client is not None:
        return _embed_client
    with _embed_client_lock:
        if _embed_client is None:
            from google import genai
            from kuro_backend.config import settings
            _embed_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _embed_client


def _cache_key(text: str) -> str:
    return hashlib.sha1(text.strip().lower().encode("utf-8", errors="replace")).hexdigest()


def _cache_get(key: str) -> Optional[tuple[float, ...]]:
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, vec = entry
        if now - ts > _CACHE_TTL_S:
            _cache.pop(key, None)
            return None
        return vec


def _cache_put(key: str, vec: Sequence[float]) -> None:
    now = time.monotonic()
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            # Drop the oldest entry (cheap O(n) because cache is small-bounded).
            oldest_key = min(_cache.items(), key=lambda kv: kv[1][0])[0]
            _cache.pop(oldest_key, None)
        _cache[key] = (now, tuple(vec))


def embed_query(text: str) -> Optional[tuple[float, ...]]:
    """Return the embedding vector for ``text`` or ``None`` on failure.

    Uses gemini-embedding-001 (768-dim) consistent with the Mem0 client so
    caches across systems share the same vector space.
    """
    if not text or not text.strip():
        return None
    key = _cache_key(text)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        client = _get_embed_client()
        result = client.models.embed_content(model=_EMBED_MODEL, contents=text)
        embeddings = getattr(result, "embeddings", None)
        if not embeddings:
            return None
        values = getattr(embeddings[0], "values", None) or getattr(embeddings[0], "embedding", None)
        if not values:
            return None
        vec = tuple(float(v) for v in values)
        _cache_put(key, vec)
        return vec
    except Exception as exc:
        logger.warning("[EMBEDDING_CACHE] embed failed: %s", exc)
        return None


def clear_cache() -> None:
    """Testing hook — wipe the in-memory cache."""
    with _cache_lock:
        _cache.clear()


__all__ = ["embed_query", "clear_cache"]
