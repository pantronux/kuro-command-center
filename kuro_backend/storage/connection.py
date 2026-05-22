"""SQLite connection manager for Storage Foundation V2."""
from __future__ import annotations

import logging
import random
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, TypeVar
from urllib.parse import quote

from kuro_backend.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


def resolve_sqlite_path(db_path: str | Path) -> Path:
    """Resolve a SQLite path against WORKING_DIR when it is relative."""
    raw = Path(str(db_path)).expanduser()
    if raw.is_absolute():
        return raw
    base = Path(getattr(settings, "WORKING_DIR", "") or ".").expanduser()
    return (base / raw).resolve()


class StorageConnectionManager:
    """Small SQLite connection helper with retry and transaction support."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        busy_timeout_ms: int | None = None,
        wal_enabled: bool = True,
        max_attempts: int = 3,
        base_delay_s: float = 0.05,
    ) -> None:
        self.db_path = db_path
        self.busy_timeout_ms = int(
            busy_timeout_ms
            if busy_timeout_ms is not None
            else getattr(settings, "KURO_DB_BUSY_TIMEOUT_MS", 5000)
        )
        self.wal_enabled = bool(wal_enabled)
        self.max_attempts = max(1, int(max_attempts))
        self.base_delay_s = max(0.0, float(base_delay_s))

    @property
    def resolved_path(self) -> Path:
        return resolve_sqlite_path(self.db_path)

    def connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        path = self.resolved_path
        if read_only:
            uri = f"file:{quote(str(path), safe='/')}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path))

        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        if self.wal_enabled and not read_only and str(path) != ":memory:":
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.OperationalError as exc:
                logger.warning("WAL mode skipped for %s: %s", path, exc)
        return conn

    def execute_with_retry(self, operation: Callable[[], T]) -> T:
        """Retry transient SQLite lock failures with exponential backoff."""
        for attempt in range(self.max_attempts):
            try:
                return operation()
            except sqlite3.OperationalError as exc:
                locked = "locked" in str(exc).lower()
                if not locked or attempt >= self.max_attempts - 1:
                    raise
                delay = self.base_delay_s * (2**attempt) + random.uniform(0, 0.025)
                logger.warning(
                    "SQLite operation locked for %s; retry %d/%d in %.3fs",
                    self.resolved_path,
                    attempt + 1,
                    self.max_attempts,
                    delay,
                )
                time.sleep(delay)
        raise RuntimeError("unreachable SQLite retry state")

    @contextmanager
    def transaction(self, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
        conn = self.connect(read_only=read_only)
        try:
            yield conn
            if not read_only:
                conn.commit()
        except Exception:
            if not read_only:
                conn.rollback()
            raise
        finally:
            conn.close()
