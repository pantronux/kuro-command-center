"""Nightly market sentinel: watched symbols vs OpenClaw price.

--- Header Doc ---
Purpose: Verify _run_market_sentinel fires on |pct| > threshold and updates finance cache.
Covers: dreaming_worker._run_market_sentinel + proactive market_alert.
Fixtures: tmp finance DB + monkeypatched _market_openclaw_price + publish spy.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def _iso_finance(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_FINANCE_DB_PATH", str(tmp_path / "ms.db"))
    monkeypatch.setenv("KURO_MARKET_SENTINEL_ENABLED", "true")
    monkeypatch.setenv("KURO_MARKET_MOVE_PCT", "2")
    monkeypatch.setenv("KURO_PREDICTION_SCAN_ENABLED", "false")
    from kuro_backend import finance_db

    finance_db.init_db()
    finance_db.upsert_watched_symbol("ZZ", "")
    finance_db.apply_watched_price("ZZ", 100.0)


def test_market_sentinel_fires_on_pct_move(monkeypatch, _iso_finance):
    published = []

    def capture(ev, dry_run=False):
        published.append(ev.kind)
        return True

    monkeypatch.setattr(
        "kuro_backend.dreaming_worker._market_openclaw_price",
        lambda sym: 104.0 if sym == "ZZ" else None,
    )
    monkeypatch.setattr("kuro_backend.proactive_events.publish", capture)

    from kuro_backend import dreaming_worker

    out = dreaming_worker._run_market_sentinel(cycle_id=7, dry_run=False)
    assert out.get("checked", 0) >= 1
    assert out.get("alerts", 0) >= 1
    assert "market_alert" in published
