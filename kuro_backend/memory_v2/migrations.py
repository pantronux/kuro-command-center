"""Memory V2 schema migrations for short-term memory table."""

# --- Header Doc ---
# Purpose: Extend legacy `short_term` table with Memory V2 metadata columns.
# Caller: memory_manager.init_short_term_db(), MemoryStore.__init__().
# Dependencies: db_utils.add_column_if_missing.
# Main Functions: extend_short_term_schema(conn).
# Side Effects: Alters sqlite schema and backfills legacy rows idempotently.

from __future__ import annotations

import logging
import sqlite3

from kuro_backend.db_utils import add_column_if_missing

logger = logging.getLogger(__name__)


def extend_short_term_schema(conn: sqlite3.Connection) -> None:
    cols = [
        ("username", "TEXT NOT NULL DEFAULT 'Pantronux'"),
        ("memory_id", "TEXT"),
        ("runtime_id", "TEXT DEFAULT 'sovereign'"),
        ("namespace", "TEXT DEFAULT 'kuro.sovereign'"),
        ("memory_type", "TEXT DEFAULT 'short_term'"),
        ("confidence", "REAL DEFAULT 1.0"),
        ("provenance_json", "TEXT DEFAULT '{}'"),
        ("expires_at", "TEXT"),
        ("status", "TEXT DEFAULT 'active'"),
        ("source", "TEXT DEFAULT 'conversation'"),
    ]
    for col_name, col_sql in cols:
        add_column_if_missing(conn, "short_term", col_name, col_sql)

    # Idempotent backfill for legacy rows.
    conn.execute(
        """
        UPDATE short_term
        SET runtime_id='sovereign', namespace='kuro.sovereign', status='active'
        WHERE runtime_id IS NULL
        """
    )
    conn.execute(
        """
        UPDATE short_term
        SET memory_id='mem_legacy_' || CAST(id AS TEXT)
        WHERE memory_id IS NULL
        """
    )
    conn.execute(
        """
        UPDATE short_term
        SET memory_type='short_term'
        WHERE memory_type IS NULL
        """
    )
    conn.execute(
        """
        UPDATE short_term
        SET confidence=1.0
        WHERE confidence IS NULL
        """
    )
    conn.execute(
        """
        UPDATE short_term
        SET provenance_json='{}'
        WHERE provenance_json IS NULL OR provenance_json = ''
        """
    )
    conn.execute(
        """
        UPDATE short_term
        SET source='conversation'
        WHERE source IS NULL OR source = ''
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_short_term_v2_scope_user_status "
        "ON short_term(namespace, runtime_id, username, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_short_term_v2_type_status "
        "ON short_term(runtime_id, namespace, memory_type, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_short_term_v2_status_expires "
        "ON short_term(status, expires_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_short_term_v2_memory_id "
        "ON short_term(memory_id)"
    )
    conn.commit()
    logger.debug("Memory V2 short_term schema ensured")
