"""Memory V3 health and safe status snapshots."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from kuro_backend.config import settings
from kuro_backend.memory_v3.store import MemoryV3Store


EXPECTED_TABLES = {
    "memory_events",
    "memory_items",
    "memory_assertions",
    "memory_links",
    "memory_conflicts",
    "memory_access_log",
    "memory_retention_policies",
    "memory_redaction_log",
    "memory_embedding_refs",
    "memory_source_refs",
}


def get_memory_v3_health(store: MemoryV3Store | None = None) -> Dict[str, Any]:
    active_store = store or MemoryV3Store()
    path = active_store.resolved_path
    exists = Path(path).exists()
    if not exists:
        return {
            "enabled": bool(getattr(settings, "KURO_MEMORY_V3_ENABLED", False)),
            "initialized": False,
            "status": "not_initialized",
            "tables_ok": False,
            "counts": {},
            "error": None,
        }
    try:
        active_store.init_db()
        tables = set(active_store.table_names())
        counts = {
            "memory_events": active_store.count_rows("memory_events"),
            "memory_items": active_store.count_rows("memory_items"),
            "memory_conflicts": active_store.count_rows("memory_conflicts"),
            "memory_access_log": active_store.count_rows("memory_access_log"),
        }
        tables_ok = EXPECTED_TABLES.issubset(tables)
        return {
            "enabled": bool(getattr(settings, "KURO_MEMORY_V3_ENABLED", False)),
            "initialized": True,
            "status": "ok" if tables_ok else "degraded",
            "tables_ok": tables_ok,
            "counts": counts,
            "error": None,
        }
    except Exception as exc:
        return {
            "enabled": bool(getattr(settings, "KURO_MEMORY_V3_ENABLED", False)),
            "initialized": exists,
            "status": "error",
            "tables_ok": False,
            "counts": {},
            "error": str(exc),
        }


def get_memory_v3_public_status(store: MemoryV3Store | None = None) -> Dict[str, Any]:
    health = get_memory_v3_health(store)
    return {
        "enabled": health["enabled"],
        "initialized": health["initialized"],
        "status": health["status"],
    }
