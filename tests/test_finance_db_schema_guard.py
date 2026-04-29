"""Schema-guard + index presence tests for V7.2.1 Natural Agency finance_db.

--- Header Doc ---
Purpose: Verify init_db() is short-circuited after the first successful bootstrap
per DB path, and that V7 hot-path indexes are created.
Covers: kuro_backend.finance_db._SCHEMA_READY_FOR guard, idx_recurring_active,
idx_watched_active.
Fixtures: tmp KURO_FINANCE_DB_PATH in tmp_path, monkeypatched _init_db_locked spy.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def isolated_finance_db(tmp_path, monkeypatch):
    db = tmp_path / "fin_guard.db"
    monkeypatch.setenv("KURO_FINANCE_DB_PATH", str(db))
    from kuro_backend import finance_db

    finance_db._reset_schema_ready_for_tests()
    yield finance_db
    finance_db._reset_schema_ready_for_tests()


def test_init_db_is_idempotent_after_first_call(isolated_finance_db, monkeypatch):
    f = isolated_finance_db

    f.init_db()

    calls = {"count": 0}
    original = f._init_db_locked

    def _spy():
        calls["count"] += 1
        return original()

    monkeypatch.setattr(f, "_init_db_locked", _spy)

    for _ in range(5):
        f.init_db()

    assert calls["count"] == 0, (
        "init_db() must short-circuit when schema is already bootstrapped; "
        f"got {calls['count']} re-initialisations"
    )


def test_schema_guard_rebootstraps_on_path_change(tmp_path, monkeypatch):
    from kuro_backend import finance_db

    finance_db._reset_schema_ready_for_tests()

    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"

    monkeypatch.setenv("KURO_FINANCE_DB_PATH", str(db_a))
    finance_db.init_db()
    assert db_a.exists()

    monkeypatch.setenv("KURO_FINANCE_DB_PATH", str(db_b))
    finance_db.init_db()
    assert db_b.exists(), "Rotating DB path must trigger a fresh bootstrap"

    finance_db._reset_schema_ready_for_tests()


def _index_list(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA index_list('{table}')")]


def test_recurring_and_watched_hot_indexes_exist(isolated_finance_db):
    f = isolated_finance_db
    f.init_db()

    conn = sqlite3.connect(f._db_path())
    try:
        recurring_idx = _index_list(conn, "recurring_expenses")
        watched_idx = _index_list(conn, "watched_symbols")
    finally:
        conn.close()

    assert "idx_recurring_active" in recurring_idx, (
        "Expected idx_recurring_active(active, label) for the active list hot path"
    )
    assert "idx_watched_active" in watched_idx, (
        "Expected idx_watched_active(active, symbol) for the dreaming sentinel hot path"
    )
