"""Small repository primitives for future Storage V2 adapters."""
from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional

from kuro_backend.storage.connection import StorageConnectionManager
from kuro_backend.storage.data_catalog import get_catalog_entry


class SQLiteRepository:
    """Read-oriented base repository that does not replace existing CRUD paths."""

    def __init__(self, connection_manager: StorageConnectionManager) -> None:
        self.connection_manager = connection_manager

    def table_exists(self, table_name: str) -> bool:
        with self.connection_manager.transaction(read_only=True) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
        return row is not None

    def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[Mapping[str, Any]]:
        with self.connection_manager.transaction(read_only=True) as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row is not None else None

    def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> List[Mapping[str, Any]]:
        with self.connection_manager.transaction(read_only=True) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]


class CatalogRepository(SQLiteRepository):
    """Repository bound to one registered logical store."""

    def __init__(self, logical_store_id: str) -> None:
        entry = get_catalog_entry(logical_store_id)
        if entry is None:
            raise ValueError(f"Unknown logical store: {logical_store_id}")
        self.entry = entry
        super().__init__(StorageConnectionManager(entry.resolved_path()))
