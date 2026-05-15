"""Memory TTL and confidence decay routines."""

# --- Header Doc ---
# Purpose: TTL-based memory expiration. Scheduled daily at 04:00 WIB.
# Caller: APScheduler in main.py.
# Dependencies: memory_store.py.
# Main Functions: expire_stale_memories(store) -> int.
# Side Effects: Updates `short_term` rows to status='expired'.

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from kuro_backend.memory_v2.memory_store import MemoryStore

logger = logging.getLogger(__name__)

DEFAULT_TTL_DAYS: dict[str, int] = {
    "short_term": 1,
    "working": 7,
    "episodic": 90,
    "semantic": 365,
    "operational": 730,
    "reflective": 365,
}


def expire_stale_memories(store: MemoryStore) -> int:
    """
    1. Set missing expires_at using TTL by memory type.
    2. Expire stale active memories.
    Returns number of memories expired in this run.
    """
    now = datetime.utcnow()
    expired_count = 0
    try:
        all_active = store.retrieve_all_active_without_expiry()
        for mem in all_active:
            ttl_days = DEFAULT_TTL_DAYS.get(mem.type, 90)
            try:
                created = datetime.fromisoformat(mem.created_at)
            except ValueError:
                created = now
            expires_at = (created + timedelta(days=ttl_days)).isoformat()
            store.set_expires_at(mem.id, expires_at)

        stale = store.retrieve_stale(as_of=now.isoformat())
        for mem in stale:
            store.expire(mem.id)
            expired_count += 1
            logger.debug(
                "Expired memory id=%r type=%r runtime=%r",
                mem.id,
                mem.type,
                mem.runtime_id,
            )
        logger.info("DecayEngine expired %s memories", expired_count)
    except Exception as exc:
        logger.error("DecayEngine failed: %s", exc, exc_info=True)
    return expired_count
