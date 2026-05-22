"""Storage health checks for admin diagnostics."""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Iterable, List

from kuro_backend.storage.connection import StorageConnectionManager
from kuro_backend.storage.data_catalog import StorageCatalogEntry, list_catalog_entries


def _read_backup_status() -> Dict[str, Any]:
    try:
        from kuro_backend import backup_manager

        return backup_manager.get_backup_status() or {}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def check_store_health(entry: StorageCatalogEntry) -> Dict[str, Any]:
    path = entry.resolved_path()
    exists = path.exists()
    result: Dict[str, Any] = {
        "logical_store_id": entry.logical_store_id,
        "db_path": str(path),
        "required_for_runtime": entry.required_for_runtime,
        "exists": exists,
        "can_open_read_only": False,
        "migration_history_exists": False,
        "wal_mode": None,
        "wal_enabled": False,
        "status": "unknown",
        "error": None,
    }

    if not exists:
        result["status"] = "missing" if entry.required_for_runtime else "optional_missing"
        return result

    manager = StorageConnectionManager(path)
    try:
        with manager.transaction(read_only=True) as conn:
            conn.execute("SELECT 1").fetchone()
            result["can_open_read_only"] = True
            table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'migration_history'"
            ).fetchone()
            result["migration_history_exists"] = table is not None
            try:
                row = conn.execute("PRAGMA journal_mode").fetchone()
                mode = str(row[0]).lower() if row else None
                result["wal_mode"] = mode
                result["wal_enabled"] = mode == "wal"
            except sqlite3.DatabaseError as exc:
                result["error"] = f"journal_mode check failed: {exc}"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        return result

    if result["can_open_read_only"]:
        result["status"] = "ok"
    return result


def get_storage_health_snapshot(
    entries: Iterable[StorageCatalogEntry] | None = None,
) -> Dict[str, Any]:
    selected = list(entries) if entries is not None else list_catalog_entries()
    stores: List[Dict[str, Any]] = [check_store_health(entry) for entry in selected]
    required_problem = any(
        store["required_for_runtime"] and store["status"] != "ok"
        for store in stores
    )
    return {
        "status": "degraded" if required_problem else "ok",
        "stores": stores,
        "last_backup_status": _read_backup_status(),
    }
