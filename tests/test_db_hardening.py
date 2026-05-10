"""DB hardening tests for retry/migration/backup integrity.

--- Header Doc ---
Purpose: Validate db_retry behavior, migration-history helpers, and backup
         integrity verification failure path.
Caller: pytest contract gate for Prompt 2 hardening.
Dependencies: db_utils, backup_manager, sqlite3.
Main Functions: test_*.
Side Effects: Uses tmp_path-only sqlite files.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kuro_backend import backup_manager
from kuro_backend.db_utils import db_retry, get_applied_version, record_migration


def test_db_retry_retries_exactly_n_times_on_locked_operational_error():
    attempts = {"count": 0}

    @db_retry(max_attempts=3, base_delay=0.0)
    def _flaky_write():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert _flaky_write() == "ok"
    assert attempts["count"] == 3


def test_migration_history_version_progression(tmp_path: Path):
    db_path = tmp_path / "migrations.db"
    conn = sqlite3.connect(db_path)
    try:
        assert get_applied_version(conn) == 0
        record_migration(conn, 1, "Initial schema baseline")
        assert get_applied_version(conn) == 1
    finally:
        conn.close()


def test_backup_integrity_check_raises_on_corrupted_file(tmp_path: Path):
    bad = tmp_path / "corrupted_backup.db"
    bad.write_bytes(b"this is not sqlite")

    with pytest.raises(RuntimeError):
        backup_manager._validate_backup_integrity(bad)
