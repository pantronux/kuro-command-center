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


def test_financial_goal_upsert_and_retrieval(isolated_finance_db):
    f = isolated_finance_db
    gid = "emergency_fund"
    f.upsert_financial_goal(gid, "Emergency Fund", 10000.0, 2500.0, "2026-12-31")

    # Verify retrieval
    goal = f.get_financial_goal(gid)
    assert goal is not None
    assert goal["name"] == "Emergency Fund"
    assert float(goal["target_amount"]) == 10000.0
    assert float(goal["current_amount"]) == 2500.0
    assert goal["deadline"] == "2026-12-31"

    # Verify update
    f.upsert_financial_goal(gid, "Emergency Fund Revised", 12000.0, 3000.0)
    updated = f.get_financial_goal(gid)
    assert updated["name"] == "Emergency Fund Revised"
    assert float(updated["target_amount"]) == 12000.0
    assert float(updated["current_amount"]) == 3000.0
    # Deadline should be NULL/None because it wasn't provided in the second upsert
    assert updated["deadline"] is None


def test_financial_goal_deletion(isolated_finance_db):
    f = isolated_finance_db
    gid = "test_goal"
    f.upsert_financial_goal(gid, "Test Goal", 100.0)

    assert f.get_financial_goal(gid) is not None
    assert f.delete_financial_goal(gid) is True
    assert f.get_financial_goal(gid) is None
    assert f.delete_financial_goal(gid) is False


def test_list_financial_goals(isolated_finance_db):
    f = isolated_finance_db
    f.upsert_financial_goal("g1", "Goal 1", 100.0)
    f.upsert_financial_goal("g2", "Goal 2", 200.0)

    goals = f.list_financial_goals()
    assert len(goals) >= 2
    slugs = [g["goal_id"] for g in goals]
    assert "g1" in slugs
    assert "g2" in slugs
