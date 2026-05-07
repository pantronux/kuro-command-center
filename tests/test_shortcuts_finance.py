"""SSoT shortcuts for finances (budget / expenses / API spend).

--- Header Doc ---
Purpose: Verify deterministic LLM bypass for Chancellor-scope factual queries.
Covers: ssot_shortcuts.match_shortcut + finance formatters.
Fixtures: tmp finance DB + seeded budget/expenses rows.
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
    monkeypatch.setenv("KURO_FINANCE_DB_PATH", str(tmp_path / "sf.db"))
    from kuro_backend import finance_db

    finance_db.init_db()
    yield finance_db


def test_budget_shortcut(isolated_finance_db):
    from kuro_backend import ssot_shortcuts

    now = __import__("datetime").datetime.now()
    month_str = now.strftime("%Y-%m")
    isolated_finance_db.add_budget(month_str, 250.0, "")
    r = ssot_shortcuts.try_shortcut("What is my budget this month?", "consultant")
    assert r is not None
    assert r.source == "finances_budget"
    assert "USD 250.00" in r.response


def test_expenses_shortcut(isolated_finance_db):
    from kuro_backend import ssot_shortcuts

    isolated_finance_db.upsert_recurring_expense(
        "Cursor", 20.0, cadence="monthly", next_due="", category="tools",
    )
    r = ssot_shortcuts.try_shortcut("list my recurring expenses", "butler")
    assert r is not None
    assert r.source == "finances_expenses"
    assert "Cursor" in r.response


def test_api_spend_shortcut(isolated_finance_db):
    from kuro_backend import ssot_shortcuts

    from datetime import date

    d = date.today().isoformat()
    isolated_finance_db.add_api_usage(d, "m", 10, 5, 0.001)
    r = ssot_shortcuts.try_shortcut("What was today's API spend?", "consultant")
    assert r is not None
    assert r.source == "finances_api_spend"
    assert "USD" in r.response
