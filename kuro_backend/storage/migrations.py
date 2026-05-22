"""Idempotent migration helpers for Storage Foundation V2."""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List

from kuro_backend.storage.connection import StorageConnectionManager
from kuro_backend.storage.data_catalog import list_catalog_entries, resolve_catalog_db_path

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(identifier: str) -> str:
    if not _IDENT_RE.match(identifier or ""):
        raise ValueError(f"Unsafe SQLite identifier: {identifier!r}")
    return f'"{identifier}"'


def ensure_table(conn: sqlite3.Connection, ddl: str) -> None:
    """Execute an idempotent table DDL statement."""
    conn.execute(ddl)
    conn.commit()


def ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column_name: str,
    column_sql: str,
) -> bool:
    """Add a SQLite column only if PRAGMA table_info shows it is missing."""
    table_sql = _quote_identifier(table)
    existing = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({table_sql})").fetchall()
    }
    if column_name in existing:
        return False
    column_sql_name = _quote_identifier(column_name)
    conn.execute(f"ALTER TABLE {table_sql} ADD COLUMN {column_sql_name} {column_sql}")
    conn.commit()
    return True


def ensure_index(
    conn: sqlite3.Connection,
    index_name: str,
    table: str,
    columns_sql: str,
) -> bool:
    """Create an index only once and report whether it was newly created."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
        (index_name,),
    ).fetchone()
    if row:
        return False
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {_quote_identifier(index_name)} "
        f"ON {_quote_identifier(table)} ({columns_sql})"
    )
    conn.commit()
    return True


def _ensure_migration_history(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migration_history (
            version INTEGER PRIMARY KEY,
            applied_at TEXT DEFAULT (datetime('now')),
            description TEXT NOT NULL
        )
        """
    )
    conn.commit()


def record_migration(db_name: str, version: int, description: str) -> None:
    """Record a migration in a catalog DB or explicit SQLite path."""
    db_path = resolve_catalog_db_path(db_name)
    manager = StorageConnectionManager(db_path)
    with manager.transaction() as conn:
        _ensure_migration_history(conn)
        conn.execute(
            "INSERT OR IGNORE INTO migration_history (version, description) VALUES (?, ?)",
            (int(version), str(description)),
        )


def get_migration_history(db_name: str) -> List[Dict[str, Any]]:
    """Read migration history from a catalog DB or explicit SQLite path."""
    db_path = resolve_catalog_db_path(db_name)
    if not db_path.exists():
        return []
    manager = StorageConnectionManager(db_path)
    with manager.transaction(read_only=True) as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'migration_history'"
        ).fetchone()
        if not table:
            return []
        rows = conn.execute(
            """
            SELECT version, applied_at, description
            FROM migration_history
            ORDER BY version ASC
            """
        ).fetchall()
    return [
        {
            "version": int(row["version"]),
            "applied_at": row["applied_at"],
            "description": row["description"],
        }
        for row in rows
    ]


def get_all_migration_histories() -> dict:
    """Return migration history for every catalog entry without mutating DBs."""
    stores = []
    for entry in list_catalog_entries():
        db_path = entry.resolved_path()
        stores.append(
            {
                "logical_store_id": entry.logical_store_id,
                "db_path": str(db_path),
                "exists": db_path.exists(),
                "migrations": get_migration_history(entry.logical_store_id),
            }
        )
    return {"stores": stores}
