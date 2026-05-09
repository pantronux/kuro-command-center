"""
Runtime isolation gate.

--- Header Doc ---
Purpose: Enforce runtime no-crossing checks for memory, db, and forbidden references.
Caller: playground runtime service and API entrypoints.
Dependencies: pathlib, sqlite3, playground_runtime.errors.
Main Functions: IsolationGate.assert_runtime_isolated().
Side Effects: Raises PlaygroundIsolationError on violations.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from playground_runtime.errors import PlaygroundIsolationError


FORBIDDEN_DB_NAMES = {
    "kuro_short_term.db",
    "kuro_chat_history.db",
    "kuro_intelligence.db",
    "kuro_auth.db",
    "kuro_finances.db",
    "kuro_compliance.db",
    "kuro_ingestion.db",
}
FORBIDDEN_TOKENS = {"mem0", "chroma", "kuro_backend", "persona", "langgraph"}


@dataclass
class IsolationGate:
    playground_db_path: Path

    def assert_db_path_isolated(self) -> None:
        name = self.playground_db_path.name
        if name in FORBIDDEN_DB_NAMES:
            raise PlaygroundIsolationError(f"BOUNDARY_VIOLATION: forbidden db name '{name}'")

    def assert_runtime_isolated(self, references: Iterable[Any]) -> None:
        """Reject suspicious object references from production runtime."""
        for ref in references:
            if ref is None:
                continue
            text = repr(ref).lower()
            if any(token in text for token in FORBIDDEN_TOKENS):
                raise PlaygroundIsolationError(
                    f"BOUNDARY_VIOLATION: forbidden runtime reference detected: {type(ref).__name__}"
                )

    def assert_sqlite_connection_isolated(self, conn: sqlite3.Connection) -> None:
        row = conn.execute("PRAGMA database_list").fetchall()
        db_paths = [r[2] for r in row if len(r) > 2]
        for path_str in db_paths:
            p = Path(path_str)
            if p.name in FORBIDDEN_DB_NAMES:
                raise PlaygroundIsolationError(
                    f"BOUNDARY_VIOLATION: sqlite connection points to production db '{p.name}'"
                )

    def enforce(self, references: Iterable[Any], conn: sqlite3.Connection | None = None) -> None:
        self.assert_db_path_isolated()
        self.assert_runtime_isolated(references)
        if conn is not None:
            self.assert_sqlite_connection_isolated(conn)
