"""Telegram hardening tests.

--- Header Doc ---
Purpose: Validate retry+DLQ, pending filter semantics, inbound limiter, and
         message length enforcement.
Caller: pytest Batch-2 hardening gate.
Dependencies: telegram_notifier, intelligence_db, main, intelligence_engine.
Main Functions: test_*.
Side Effects: Uses tmp intelligence DB only.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
import types
from pathlib import Path

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

if "phoenix" not in sys.modules:
    fake_phoenix = types.ModuleType("phoenix")

    class _FakePhoenixApp:
        url = "http://localhost:6006"

        def close(self):
            return None

    def _launch_app(*args, **kwargs):
        return _FakePhoenixApp()

    fake_phoenix.launch_app = _launch_app
    sys.modules["phoenix"] = fake_phoenix

import main
from kuro_backend import intelligence_db, telegram_notifier
from kuro_backend.intelligence_engine import format_telegram_message


class _Resp500:
    status_code = 500
    text = "internal error"


def test_send_message_with_retry_retries_then_logs_dlq(tmp_path, monkeypatch):
    db_path = tmp_path / "intel.db"
    monkeypatch.setattr(intelligence_db, "DB_PATH", str(db_path), raising=False)
    intelligence_db._reset_schema_ready_for_tests()
    intelligence_db.init_db()

    calls = {"count": 0}

    async def _fake_post(payload, timeout_s=10.0):
        calls["count"] += 1
        return _Resp500()

    monkeypatch.setattr(telegram_notifier, "_post_to_telegram", _fake_post)
    monkeypatch.setattr(telegram_notifier, "_is_telegram_enabled", lambda: True)
    monkeypatch.setattr(telegram_notifier, "_resolve_chat_targets", lambda chat_id=None: ["12345"])

    ok = asyncio.run(telegram_notifier.send_message_with_retry("hello", max_attempts=3))

    assert ok is False
    assert calls["count"] == 3
    pending = intelligence_db.get_pending_failed_notifications(max_attempts=5)
    assert len(pending) >= 1


def test_get_pending_failed_notifications_filters_attempts_and_status(tmp_path, monkeypatch):
    db_path = tmp_path / "intel_pending.db"
    monkeypatch.setattr(intelligence_db, "DB_PATH", str(db_path), raising=False)
    intelligence_db._reset_schema_ready_for_tests()
    intelligence_db.init_db()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO failed_telegram_notifications (payload_json, error_message, attempt_count, status) VALUES (?, ?, ?, ?)",
            ('{"chat_id":"1","text":"a"}', "err", 0, "pending"),
        )
        conn.execute(
            "INSERT INTO failed_telegram_notifications (payload_json, error_message, attempt_count, status) VALUES (?, ?, ?, ?)",
            ('{"chat_id":"1","text":"b"}', "err", 5, "pending"),
        )
        conn.execute(
            "INSERT INTO failed_telegram_notifications (payload_json, error_message, attempt_count, status) VALUES (?, ?, ?, ?)",
            ('{"chat_id":"1","text":"c"}', "err", 1, "dead"),
        )
        conn.commit()
    finally:
        conn.close()

    rows = intelligence_db.get_pending_failed_notifications(max_attempts=5)
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["attempt_count"] < 5


def test_telegram_rate_limiter_allows_first_10_blocks_11th():
    main._tg_rate_buckets.clear()

    allowed = [main._check_telegram_rate_limit("chat-1", 10) for _ in range(11)]

    assert all(allowed[:10])
    assert allowed[10] is False


def test_format_telegram_message_is_capped_to_4096_chars():
    long_text = "x" * 10000
    briefing = {
        "date": "2026-05-09",
        "status_pagi": long_text,
        "intelijen_sektoral": long_text,
        "wawasan_teknologi": long_text,
        "wawasan_finansial": long_text,
        "rekomendasi_eksperimental": [long_text, long_text, long_text],
        "catatan_kesehatan": long_text,
        "penutup": long_text,
    }

    msg = format_telegram_message(briefing)
    assert len(msg) <= 4096
