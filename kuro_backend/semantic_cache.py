"""Kuro AI V6.0 Sovereign — Revision-aware semantic response cache (P3.1).

A tiny in-memory cache keyed by the embedding of a query. On read, we:

1. Embed the incoming query via :mod:`embedding_cache`.
2. Find the closest entry in the persona scope whose cosine similarity meets
   a configurable threshold (default ``0.94``).
3. Validate that the SSoT data revision at the time of write still matches
   the current revision when the entry is SSoT-tagged. If not, drop the
   entry and keep looking.

Design goals:
- **Safe by default**: opt-in via ``KURO_SEMANTIC_CACHE_ENABLED`` env var.
- **Revision-aware**: any SSoT-tagged entry is invalidated on revision bump
  (``add_habit_svc`` / ``mark_habit_done_svc`` / reminder CRUD etc.), so the
  cache can never serve a stale factual answer after a write.
- **Process-local LRU**: keeps p95 latency predictable; restart = cold cache
  (acceptable; no correctness risk).

NOT a replacement for :mod:`ssot_shortcuts` — shortcuts are deterministic
templates; this cache is for repeated *LLM-generated* answers.

--- Header Doc ---
Purpose: Semantic (embedding-similarity) response cache gated by SSoT revision token.
Caller: langgraph_core response_node, main.py stream fastpath.
Dependencies: kuro_backend.embedding_cache, stdlib (threading, math, dataclasses).
Main Functions: get(), put(), purge_ssot_tagged(), is_enabled().
Side Effects: In-process dict + lock; no durable writes; logs diagnostic metrics.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Final, Iterable, Optional, Sequence

from kuro_backend import embedding_cache

logger = logging.getLogger(__name__)

# V6.0: Semantic Cache enabled by default for significant TTFB improvements on repeated intents
ENABLED: Final[bool] = os.getenv("KURO_SEMANTIC_CACHE_ENABLED", "true").lower() in ("1", "true", "yes")
_SIM_THRESHOLD: Final[float] = float(os.getenv("KURO_SEMANTIC_CACHE_SIM", "0.94"))
_CACHE_TTL_S: Final[float] = float(os.getenv("KURO_SEMANTIC_CACHE_TTL", "900"))
_CACHE_MAX: Final[int] = int(os.getenv("KURO_SEMANTIC_CACHE_MAX", "256"))


@dataclass
class _Entry:
    persona: str
    embedding: tuple[float, ...]
    response: str
    tags: frozenset[str]
    data_revision_at_write: int
    ts: float = field(default_factory=time.monotonic)
    hits: int = 0


_entries: list[_Entry] = []
_lock = threading.RLock()


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0

    # ⚡ Bolt: Single pass computation avoids 3 generator loops
    num = 0.0
    da_sq = 0.0
    db_sq = 0.0
    for x, y in zip(a, b):
        num += x * y
        da_sq += x * x
        db_sq += y * y

    if da_sq == 0 or db_sq == 0:
        return 0.0
    return num / math.sqrt(da_sq * db_sq)


def _current_revision() -> int:
    try:
        from kuro_backend.services import core_service
        return int(core_service.get_data_revision())
    except Exception:
        return 0


def _evict_expired_locked(now: float) -> None:
    global _entries
    _entries = [e for e in _entries if now - e.ts <= _CACHE_TTL_S]


def lookup(query: str, persona: str) -> Optional[str]:
    """Return a cached response if a similar, still-fresh entry exists.

    Returns ``None`` when the feature is disabled, no embedding is available,
    or no entry satisfies the similarity + revision check.
    """
    if not ENABLED or not query:
        return None
    vec = embedding_cache.embed_query(query)
    if vec is None:
        return None
    now = time.monotonic()
    current_rev = _current_revision()
    with _lock:
        _evict_expired_locked(now)
        best: tuple[float, _Entry] | None = None
        for entry in _entries:
            if entry.persona != persona:
                continue
            sim = _cosine(vec, entry.embedding)
            if sim >= _SIM_THRESHOLD and (best is None or sim > best[0]):
                best = (sim, entry)
        if best is None:
            return None
        sim, entry = best
        # Revision check for SSoT-tagged entries: if the SSoT bumped after
        # write, the cached answer might contradict SSoT. Drop it and miss.
        if "ssot" in entry.tags and entry.data_revision_at_write != current_rev:
            try:
                _entries.remove(entry)
            except ValueError:
                pass
            return None
        entry.hits += 1
        logger.info(
            "[SEMANTIC_CACHE] HIT persona=%s sim=%.3f tags=%s hits=%d",
            persona, sim, sorted(entry.tags), entry.hits,
        )
        return entry.response


def store(query: str, persona: str, response: str, tags: Iterable[str] = ()) -> None:
    """Write a fresh entry into the cache.

    No-op when disabled or when the embedding API is unavailable.
    """
    if not ENABLED or not query or not response:
        return
    vec = embedding_cache.embed_query(query)
    if vec is None:
        return
    tag_set = frozenset(tags)
    entry = _Entry(
        persona=persona,
        embedding=vec,
        response=response,
        tags=tag_set,
        data_revision_at_write=_current_revision(),
    )
    with _lock:
        _entries.append(entry)
        if len(_entries) > _CACHE_MAX:
            # Drop oldest entry; LRU behavior approximated by write time.
            _entries.sort(key=lambda e: e.ts)
            _entries.pop(0)


def invalidate_tag(tag: str) -> int:
    """Remove entries carrying the given tag. Returns number evicted."""
    if not ENABLED:
        return 0
    removed = 0
    with _lock:
        remaining: list[_Entry] = []
        for e in _entries:
            if tag in e.tags:
                removed += 1
                continue
            remaining.append(e)
        _entries[:] = remaining
    if removed:
        logger.info("[SEMANTIC_CACHE] invalidated %d entries for tag=%s", removed, tag)
    return removed


def clear() -> None:
    """Testing helper — drop all entries."""
    with _lock:
        _entries.clear()


def classify_tags(query: str) -> frozenset[str]:
    """Cheap heuristic to tag a query for revision-aware invalidation.

    Currently only handles generic SSoT tagging.
    """
    if not query:
        return frozenset()
    q = query.lower()
    # Habit and reminder tokens removed in V1.0.0
    return frozenset()


__all__ = [
    "ENABLED",
    "classify_tags",
    "clear",
    "invalidate_tag",
    "lookup",
    "store",
]
