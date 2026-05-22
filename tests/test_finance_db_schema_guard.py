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

    assert "idx_recurring_active_user" in recurring_idx, (
        "Expected idx_recurring_active_user(active, username, label) for the active list hot path"
    )
    assert "idx_watched_active_user" in watched_idx, (
        "Expected idx_watched_active_user(active, username, symbol) for the dreaming sentinel hot path"
    )


def test_legacy_market_hud_snapshot_gets_username_conflict_target(tmp_path, monkeypatch):
    from kuro_backend import finance_db

    db = tmp_path / "legacy_finance.db"
    monkeypatch.setenv("KURO_FINANCE_DB_PATH", str(db))
    finance_db._reset_schema_ready_for_tests()

    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            CREATE TABLE market_hud_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_text TEXT NOT NULL DEFAULT '',
                last_sentinel_note TEXT NOT NULL DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now')),
                username TEXT NOT NULL DEFAULT 'Pantronux'
            )
            """
        )
        conn.execute(
            "INSERT INTO market_hud_snapshot (username, brief_text) VALUES ('Pantronux', 'old')"
        )
        conn.commit()
    finally:
        conn.close()

    finance_db.init_db()
    finance_db.touch_market_snapshot_fetched_at("Pantronux")

    conn = sqlite3.connect(db)
    try:
        indexes = _index_list(conn, "market_hud_snapshot")
        row_count = conn.execute(
            "SELECT COUNT(*) FROM market_hud_snapshot WHERE username = 'Pantronux'"
        ).fetchone()[0]
    finally:
        conn.close()
        finance_db._reset_schema_ready_for_tests()

    assert "idx_market_hud_snapshot_username_unique" in indexes
    assert row_count == 1


def test_market_sentinel_stocks_are_user_scoped_and_chart_history_records_prices(isolated_finance_db):
    f = isolated_finance_db
    f.init_db()

    assert f.upsert_sentinel_stock_price(
        stock_code="MDKA",
        company_name="MDKA",
        sector="IDX",
        price_per_share=2550,
        price_per_lot=255000,
        price_category="below_500k",
        volume_24h=10,
        ytd_performance=0.0,
        username="Pantronux",
    )
    assert f.upsert_sentinel_stock_price(
        stock_code="MDKA",
        company_name="MDKA",
        sector="IDX",
        price_per_share=2600,
        price_per_lot=260000,
        price_category="below_500k",
        volume_24h=20,
        ytd_performance=0.0,
        username="Faikhira",
    )

    pantronux = f.get_sentinel_stock_detail("MDKA", username="Pantronux")
    faikhira = f.get_sentinel_stock_detail("MDKA", username="Faikhira")
    chart = f.get_sentinel_history_for_chart("MDKA", username="Pantronux")

    assert pantronux["current_price_per_share"] == 2550
    assert faikhira["current_price_per_share"] == 2600
    assert chart
    assert chart[-1]["price_per_share"] == 2550
