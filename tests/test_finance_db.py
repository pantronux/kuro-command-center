"""Tests for finances SSoT (kuro_finances.db schema + UPSERT semantics).

--- Header Doc ---
Purpose: Verify budget / recurring / api_usage / watched_symbol / prediction CRUD + apply_watched_price.
Covers: kuro_backend.finance_db helpers end-to-end.
Fixtures: tmp KURO_FINANCE_DB_PATH in tmp_path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def isolated_finance_db(tmp_path, monkeypatch):
    db = tmp_path / "fin_test.db"
    monkeypatch.setenv("KURO_FINANCE_DB_PATH", str(db))
    from kuro_backend import finance_db

    finance_db.init_db()
    yield finance_db


def test_budget_upsert(isolated_finance_db):
    f = isolated_finance_db
    f.add_budget("2026-04", 500.0, "Q2")
    f.add_budget("2026-04", 600.0, "revised")
    row = f.get_budget("2026-04")
    assert row is not None
    assert float(row["amount_usd"]) == 600.0
    assert "revised" in (row.get("notes") or "")


def test_api_usage_daily_accumulates(isolated_finance_db):
    f = isolated_finance_db
    d = "2026-04-16"
    f.add_api_usage(d, "gemini-test", 100, 50, 0.01)
    f.add_api_usage(d, "gemini-test", 200, 100, 0.02)
    assert f.get_daily_api_cost_usd(d) == pytest.approx(0.03)


def test_recurring_expense_roundtrip(isolated_finance_db):
    f = isolated_finance_db
    rid = f.upsert_recurring_expense(
        "Cloud VPS", 12.5, cadence="monthly", next_due="2026-05-01",
        category="infra", active=True,
    )
    assert rid > 0
    rows = f.list_recurring_expenses(active_only=True)
    assert any(r["label"] == "Cloud VPS" for r in rows)
    assert f.delete_recurring_expense(rid) is True
    rows2 = f.list_recurring_expenses(active_only=True)
    assert not any(r["label"] == "Cloud VPS" for r in rows2)


def test_watched_symbol_price_tick(isolated_finance_db):
    f = isolated_finance_db
    f.upsert_watched_symbol("ZZ", "Test")
    f.apply_watched_price("ZZ", 100.0)
    row = f.get_watched_symbol("ZZ")
    assert row is not None
    assert float(row["last_price"]) == 100.0
    assert row["last_pct_change"] is None or float(row["last_pct_change"] or 0) == 0.0
    f.apply_watched_price("ZZ", 105.0)
    row2 = f.get_watched_symbol("ZZ")
    assert float(row2["last_pct_change"]) == pytest.approx(5.0)
    assert f.delete_watched_symbol("ZZ") is True


def test_prediction_watch_and_hud(isolated_finance_db):
    f = isolated_finance_db
    f.upsert_prediction_watch("t1", "Topic one", 0.5, trend="up")
    rows = f.list_prediction_watch()
    assert any(r["slug"] == "t1" for r in rows)
    hud = f.get_market_hud_items()
    assert any(x["id"] == "t1" for x in hud)
    f.delete_prediction_watch("t1")
