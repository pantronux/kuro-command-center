#!/usr/bin/env python3
"""Delete Mem0 memories containing known bad substrings (hallucinated model/IP). Repo root + .env."""
from __future__ import annotations

import json
import logging
import sys
from typing import Any, List

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Substrings to purge (case-insensitive).
JUNK_MARKERS = (
    "gemini 2.5",
    "gemini2.5",
    "192.168.18.216",
)


def _coerce_rows(raw: Any) -> List[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("results", "memories", "data", "items"):
            val = raw.get(key)
            if isinstance(val, list):
                return val
    return []


def _memory_blob(row: Any) -> str:
    if isinstance(row, str):
        return row
    if not isinstance(row, dict):
        return str(row)
    parts: List[str] = []
    for k in ("memory", "text", "content", "data"):
        v = row.get(k)
        if isinstance(v, str):
            parts.append(v)
    meta = row.get("metadata")
    if meta is not None:
        try:
            parts.append(json.dumps(meta, ensure_ascii=False))
        except (TypeError, ValueError):
            parts.append(str(meta))
    return " ".join(parts)


def _memory_id(row: Any) -> str | None:
    if not isinstance(row, dict):
        return None
    for k in ("id", "memory_id", "_id", "uuid"):
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def _matches_junk(blob: str) -> bool:
    low = blob.lower()
    for m in JUNK_MARKERS:
        if m.lower() in low:
            return True
    if "gemini" in low and "2.5" in low:
        return True
    return False


def main() -> int:
    from kuro_backend.perpetual_memory import perpetual_memory

    pm = perpetual_memory
    if not pm.client:
        logger.error("Mem0 client unavailable — check API keys / Qdrant path.")
        return 1

    try:
        raw = pm.client.get_all(user_id=pm.user_id, limit=5000)
    except Exception as e:
        logger.error("get_all failed: %s", e)
        return 1

    rows = _coerce_rows(raw)
    deleted = 0
    for row in rows:
        blob = _memory_blob(row)
        if not _matches_junk(blob):
            continue
        mid = _memory_id(row)
        if not mid:
            logger.warning("Junk memory but no id (skipped): %s...", blob[:120])
            continue
        pm.delete_memory(mid)
        deleted += 1

    logger.info("Purge complete: deleted %s memories matching junk markers.", deleted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
