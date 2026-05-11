"""Market hardening tests.

--- Header Doc ---
Purpose: Validate snapshot staleness checks, atomic HUD writes, alert dedup,
         and circuit-breaker transitions.
Caller: pytest Batch-2 hardening gate.
Dependencies: finance_db, market_sentinel, openclaw_bridge, memory_manager.
Main Functions: test_*.
Side Effects: Uses tmp sqlite DBs and monkeypatch stubs.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *args, **kwargs):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

from kuro_backend import finance_db, market_sentinel, memory_manager
from kuro_backend.execution import openclaw_bridge


def test_is_snapshot_stale_true_for_old_fetched_at(tmp_path, monkeypatch):
    db_path = tmp_path / "finance.db"
    monkeypatch.setenv("KURO_FINANCE_DB_PATH", str(db_path))
    finance_db._reset_schema_ready_for_tests()
    finance_db.init_db()

    conn = sqlite3.connect(db_path)
    try:
        old_ts = (datetime.utcnow() - timedelta(minutes=61)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE market_hud_snapshot SET fetched_at = ? WHERE username = ?",
            (old_ts, "Pantronux"),
        )
        conn.commit()
    finally:
        conn.close()

    assert finance_db.is_snapshot_stale(15, username="Pantronux") is True


def test_write_hud_snapshot_atomic_keeps_single_current_row(tmp_path, monkeypatch):
    db_path = tmp_path / "finance_atomic.db"
    monkeypatch.setenv("KURO_FINANCE_DB_PATH", str(db_path))
    finance_db._reset_schema_ready_for_tests()
    finance_db.init_db()

    def _writer(i: int):
        finance_db.write_hud_snapshot_atomic(
            {
                "username": "Pantronux",
                "brief_text": f"brief-{i}",
                "last_sentinel_note": f"note-{i}",
            }
        )

    with ThreadPoolExecutor(max_workers=4) as exe:
        list(exe.map(_writer, range(8)))

    conn = sqlite3.connect(db_path)
    try:
        cur_count = conn.execute(
            "SELECT COUNT(*) FROM market_hud_snapshot WHERE is_current = 1"
        ).fetchone()[0]
    finally:
        conn.close()

    assert cur_count == 1


def test_market_alert_dedup_suppresses_second_publish(tmp_path, monkeypatch):
    short_term_db = tmp_path / "short_term.db"
    monkeypatch.setattr(memory_manager, "SHORT_TERM_DB", str(short_term_db), raising=False)
    memory_manager._reset_short_term_schema_ready_for_tests()
    memory_manager.init_short_term_db()

    monkeypatch.setenv("ADMIN_USERNAME", "Pantronux")

    monkeypatch.setattr(market_sentinel, "get_all_sentinel_stocks", lambda username="Pantronux": [{"stock_code": "BBCA", "current_price_per_lot": 1000, "volume_24h": 1, "ytd_performance": 0.0}])
    monkeypatch.setattr(market_sentinel, "fetch_macro_context", lambda: "macro")
    monkeypatch.setattr(market_sentinel, "fetch_prediction_sentiment", lambda: "sentiment")
    monkeypatch.setattr(market_sentinel, "triangulate_analysis", lambda stocks, macro, sentiment: [{"stock_code": "BBCA", "projected_roi_1m": 1.0, "projected_roi_1y": 2.0, "triangulation_summary": "ok", "conclusion": "WORTH BUYING"}])
    monkeypatch.setattr(market_sentinel, "update_sentinel_stock_analysis", lambda **kwargs: True)
    monkeypatch.setattr(market_sentinel, "is_snapshot_stale", lambda threshold, username="Pantronux": False)

    sent = {"count": 0}

    async def _fake_send(msg, chat_id=None, max_attempts=3):
        sent["count"] += 1
        return True

    monkeypatch.setattr(market_sentinel.telegram_notifier, "send_message_with_retry", _fake_send)

    assert market_sentinel.run_triangulation_scan(username="Pantronux") is True
    assert market_sentinel.run_triangulation_scan(username="Pantronux") is True
    assert sent["count"] == 1


def test_openclaw_circuit_transitions_to_open_and_half_open(monkeypatch):
    # Explicitly enable so circuit breaker transitions can be tested
    # regardless of the .env default (OPENCLAW_ENABLED=false).
    monkeypatch.setenv("OPENCLAW_ENABLED", "true")
    openclaw_bridge._reset_circuit_breaker()

    def _raise_conn(*args, **kwargs):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(openclaw_bridge, "_post_openclaw_blocking", _raise_conn)

    for _ in range(5):
        openclaw_bridge.execute_openclaw_skill_blocking("prediction_market_scan", {"execution_mode": "readonly"})

    assert openclaw_bridge.get_circuit_state() == "open"

    opened_at = openclaw_bridge._circuit_opened_at
    monkeypatch.setattr(openclaw_bridge.time, "monotonic", lambda: opened_at + openclaw_bridge.OPENCLAW_CIRCUIT_BREAKER_COOLDOWN_SECONDS + 1)
    assert openclaw_bridge._try_begin_half_open_probe() is True
    assert openclaw_bridge.get_circuit_state() == "half-open"

