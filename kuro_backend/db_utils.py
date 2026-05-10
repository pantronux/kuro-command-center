"""
Kuro AI V6.0 Sovereign - Shared SQLite Utility Layer
================================================================================

--- Header Doc ---
Purpose: Shared SQLite connection utilities and retry decorator for DB modules.
Caller: *_db.py modules, memory_manager.py, services/core_service.py.
Dependencies: sqlite3, functools, random, time, kuro_backend.config.
Main Functions: get_connection(), db_retry(), ensure_migration_history(),
                get_applied_version(), record_migration().
Side Effects: get_connection sets WAL + busy timeout pragmas on each connection.
"""
from __future__ import annotations

import functools
import logging
import random
import sqlite3
import time
from typing import Callable

from kuro_backend.config import settings

logger = logging.getLogger(__name__)


def get_connection(db_path: str) -> sqlite3.Connection:
    """Open a sqlite connection with consistent runtime pragmas."""
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA busy_timeout = {int(getattr(settings, 'KURO_DB_BUSY_TIMEOUT_MS', 5000) or 5000)}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def db_retry(max_attempts: int = 3, base_delay: float = 0.1):
    """Retry sqlite write operations that fail due to transient DB locks."""
    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except sqlite3.OperationalError as exc:
                    message = str(exc).lower()
                    if "locked" in message and attempt < max_attempts - 1:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 0.05)
                        logger.warning(
                            "DB locked (%s), retry %d/%d in %.2fs",
                            fn.__name__,
                            attempt + 1,
                            max_attempts,
                            delay,
                        )
                        time.sleep(delay)
                        continue
                    raise
        return wrapper
    return decorator


def ensure_migration_history(conn: sqlite3.Connection) -> None:
    """Ensure migration history table exists in the active DB."""
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


def get_applied_version(conn: sqlite3.Connection) -> int:
    """Return the latest applied migration version for this DB."""
    ensure_migration_history(conn)
    row = conn.execute("SELECT MAX(version) FROM migration_history").fetchone()
    return int((row[0] if row else 0) or 0)


def record_migration(conn: sqlite3.Connection, version: int, description: str) -> None:
    """Record a migration as applied exactly once."""
    conn.execute(
        "INSERT OR IGNORE INTO migration_history (version, description) VALUES (?, ?)",
        (int(version), str(description)),
    )
    conn.commit()


__all__ = [
    "db_retry",
    "ensure_migration_history",
    "get_applied_version",
    "get_connection",
    "record_migration",
]
