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


DECAY_BATCH_SIZE = 500


def expire_stale_memories(store: MemoryStore) -> int:
    """
    1. Set missing expires_at using TTL by memory type.
    2. Expire stale active memories.
    Returns number of memories expired in this run.
    """
    now = datetime.utcnow()
    expired_count = 0
    try:
        if hasattr(store.__class__, "iter_active_without_expiry"):
            active_iter = store.iter_active_without_expiry(batch_size=DECAY_BATCH_SIZE)
        else:
            active_iter = iter(store.retrieve_all_active_without_expiry())
        expiry_updates: list[tuple[str, str]] = []
        for mem in active_iter:
            ttl_days = DEFAULT_TTL_DAYS.get(mem.type, 90)
            try:
                created = datetime.fromisoformat(mem.created_at)
            except ValueError:
                created = now
            expires_at = (created + timedelta(days=ttl_days)).isoformat()
            expiry_updates.append((mem.id, expires_at))
            if len(expiry_updates) >= DECAY_BATCH_SIZE:
                if hasattr(store.__class__, "set_expires_at_many"):
                    store.set_expires_at_many(expiry_updates)
                else:
                    for memory_id, expires in expiry_updates:
                        store.set_expires_at(memory_id, expires)
                expiry_updates = []
        if expiry_updates:
            if hasattr(store.__class__, "set_expires_at_many"):
                store.set_expires_at_many(expiry_updates)
            else:
                for memory_id, expires in expiry_updates:
                    store.set_expires_at(memory_id, expires)

        if hasattr(store.__class__, "iter_stale"):
            stale_iter = store.iter_stale(as_of=now.isoformat(), batch_size=DECAY_BATCH_SIZE)
        else:
            stale_iter = iter(store.retrieve_stale(as_of=now.isoformat()))
        expire_ids: list[str] = []
        for mem in stale_iter:
            expire_ids.append(mem.id)
            if len(expire_ids) >= DECAY_BATCH_SIZE:
                if hasattr(store.__class__, "expire_many"):
                    store.expire_many(expire_ids)
                else:
                    for memory_id in expire_ids:
                        store.expire(memory_id)
                expired_count += len(expire_ids)
                expire_ids = []
            logger.debug(
                "Expired memory id=%r type=%r runtime=%r",
                mem.id,
                mem.type,
                mem.runtime_id,
            )
        if expire_ids:
            if hasattr(store.__class__, "expire_many"):
                store.expire_many(expire_ids)
            else:
                for memory_id in expire_ids:
                    store.expire(memory_id)
            expired_count += len(expire_ids)
        logger.info("DecayEngine expired %s memories", expired_count)
    except Exception as exc:
        logger.error("DecayEngine failed: %s", exc, exc_info=True)
    return expired_count
