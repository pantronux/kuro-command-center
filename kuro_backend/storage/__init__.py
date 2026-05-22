"""Storage Foundation V2 utilities.

This package is additive: it provides future-ready storage helpers without
replacing existing SQLite runtime paths.
"""
from __future__ import annotations

from .connection import StorageConnectionManager
from .data_catalog import StorageCatalogEntry, get_storage_catalog_snapshot, list_catalog_entries
from .health import get_storage_health_snapshot
from .migrations import (
    ensure_column,
    ensure_index,
    ensure_table,
    get_migration_history,
    record_migration,
)

__all__ = [
    "StorageCatalogEntry",
    "StorageConnectionManager",
    "ensure_column",
    "ensure_index",
    "ensure_table",
    "get_migration_history",
    "get_storage_catalog_snapshot",
    "get_storage_health_snapshot",
    "list_catalog_entries",
    "record_migration",
]
