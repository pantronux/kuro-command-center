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
from kuro_backend.intelligence_engine import build_status_pagi, format_telegram_message


class _Resp500:
    status_code = 500
    text = "internal error"


class _FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id


class _FakeMessage:
    def __init__(self, text):
        self.text = text


class _FakeUpdate:
    def __init__(self, chat_id="12345", text="hello"):
        self.effective_chat = _FakeChat(chat_id)
        self.message = _FakeMessage(text)


class _FakeBot:
    def __init__(self):
        self.messages = []
        self.actions = []

    async def send_message(self, chat_id, text):
        self.messages.append({"chat_id": str(chat_id), "text": text})

    async def send_chat_action(self, chat_id, action):
        self.actions.append({"chat_id": str(chat_id), "action": action})


class _InlineApplication:
    def __init__(self):
        self.tasks = []

    def create_task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task


class _FakeContext:
    def __init__(self, bot=None, application=None):
        self.bot = bot or _FakeBot()
        self.application = application


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


def test_failed_notification_dedupe_and_limit(tmp_path, monkeypatch):
    db_path = tmp_path / "intel_dedupe.db"
    monkeypatch.setattr(intelligence_db, "DB_PATH", str(db_path), raising=False)
    intelligence_db._reset_schema_ready_for_tests()
    intelligence_db.init_db()

    payload = '{"chat_id":"1","text":"same"}'
    first_id = intelligence_db.log_failed_notification(payload, "err-1")
    second_id = intelligence_db.log_failed_notification(payload, "err-2")
    intelligence_db.log_failed_notification('{"chat_id":"1","text":"other"}', "err-3")

    assert first_id == second_id
    rows = intelligence_db.get_pending_failed_notifications(max_attempts=5, limit=1)
    assert len(rows) == 1

    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM failed_telegram_notifications").fetchone()[0]
        latest_error = conn.execute(
            "SELECT error_message FROM failed_telegram_notifications WHERE id = ?",
            (first_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == 2
    assert latest_error == "err-2"


def test_send_message_with_retry_can_skip_dlq_recording(tmp_path, monkeypatch):
    db_path = tmp_path / "intel_no_dlq.db"
    monkeypatch.setattr(intelligence_db, "DB_PATH", str(db_path), raising=False)
    intelligence_db._reset_schema_ready_for_tests()
    intelligence_db.init_db()

    async def _fake_post(payload, timeout_s=10.0):
        return _Resp500()

    monkeypatch.setattr(telegram_notifier, "_post_to_telegram", _fake_post)
    monkeypatch.setattr(telegram_notifier, "_is_telegram_enabled", lambda: True)
    monkeypatch.setattr(telegram_notifier, "_resolve_chat_targets", lambda chat_id=None: ["12345"])

    ok = asyncio.run(
        telegram_notifier.send_message_with_retry(
            "hello",
            max_attempts=1,
            record_failure=False,
        )
    )

    assert ok is False
    assert intelligence_db.get_pending_failed_notifications(max_attempts=5) == []


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


def test_build_status_pagi_uses_real_metric_shape():
    msg = build_status_pagi()

    assert "CPU:" in msg
    assert "RAM:" in msg
    assert "Disk:" in msg
    assert "WIB" in msg
    assert "128GB" not in msg


def test_telegram_enabled_alias_prefers_new_env(monkeypatch):
    monkeypatch.setenv("KURO_DREAMING_TELEGRAM_ENABLED", "false")
    monkeypatch.setenv("KURO_TELEGRAM_ENABLED", "true")

    assert telegram_notifier._is_telegram_enabled() is True


def test_split_text_for_telegram_chunks_long_messages():
    chunks = telegram_notifier.split_text_for_telegram("x" * 9000)

    assert len(chunks) == 3
    assert all(len(chunk) <= 4000 for chunk in chunks)
    assert "".join(chunks) == "x" * 9000


def test_telegram_admin_allowlist_supports_comma_separated(monkeypatch):
    monkeypatch.setattr(main.settings, "TELEGRAM_CHAT_ID", "111, 222,333", raising=False)

    assert main._is_authorized_telegram_chat("222") is True
    assert main._is_authorized_telegram_chat("999") is False


def test_handle_message_rejects_unauthorized_chat(monkeypatch):
    monkeypatch.setattr(main.settings, "TELEGRAM_CHAT_ID", "12345", raising=False)
    bot = _FakeBot()
    ctx = _FakeContext(bot=bot)

    asyncio.run(main.handle_message(_FakeUpdate(chat_id="999", text="hello"), ctx))

    assert "only authorized" in bot.messages[-1]["text"]


def test_handle_message_acknowledges_and_schedules_background(monkeypatch):
    monkeypatch.setattr(main.settings, "TELEGRAM_CHAT_ID", "12345", raising=False)
    monkeypatch.setattr(main, "_check_telegram_rate_limit", lambda chat_id, limit: True)
    monkeypatch.setattr(main.chat_history, "add_message", lambda *args, **kwargs: 1)
    monkeypatch.setattr(main, "process_chat_with_graph", lambda *args, **kwargs: "jawaban")
    monkeypatch.setattr(main.auth_db, "get_user", lambda username: {"master_name": "Master"})
    bot = _FakeBot()
    app = _InlineApplication()
    ctx = _FakeContext(bot=bot, application=app)

    async def _run():
        await main.handle_message(_FakeUpdate(chat_id="12345", text="halo"), ctx)
        await asyncio.gather(*app.tasks)

    asyncio.run(_run())

    assert bot.messages[0]["text"].startswith("Diterima")
    assert bot.messages[-1]["text"] == "jawaban"


def test_rate_limited_message_is_processed_by_queue_worker(monkeypatch):
    monkeypatch.setattr(main.settings, "TELEGRAM_CHAT_ID", "12345", raising=False)
    monkeypatch.setattr(main, "_check_telegram_rate_limit", lambda chat_id, limit: False)
    monkeypatch.setattr(main.chat_history, "add_message", lambda *args, **kwargs: 1)
    monkeypatch.setattr(main, "process_chat_with_graph", lambda *args, **kwargs: "queued answer")
    monkeypatch.setattr(main.auth_db, "get_user", lambda username: {"master_name": "Master"})
    bot = _FakeBot()
    ctx = _FakeContext(bot=bot)

    async def _run():
        while not main._tg_inbound_queue.empty():
            main._tg_inbound_queue.get_nowait()
            main._tg_inbound_queue.task_done()
        await main.handle_message(_FakeUpdate(chat_id="12345", text="queued"), ctx)
        await main._telegram_inbound_queue_worker(bot, max_items=1)

    asyncio.run(_run())

    assert any("antrian" in msg["text"].lower() for msg in bot.messages)
    assert bot.messages[-1]["text"] == "queued answer"


def test_queue_full_returns_fallback(monkeypatch):
    monkeypatch.setattr(main.settings, "TELEGRAM_CHAT_ID", "12345", raising=False)
    monkeypatch.setattr(main, "_check_telegram_rate_limit", lambda chat_id, limit: False)

    class _FullQueue:
        maxsize = 1

        def put_nowait(self, payload):
            raise asyncio.QueueFull

    old_queue = main._tg_inbound_queue
    monkeypatch.setattr(main, "_tg_inbound_queue", _FullQueue())
    bot = _FakeBot()
    ctx = _FakeContext(bot=bot)
    try:
        asyncio.run(main.handle_message(_FakeUpdate(chat_id="12345", text="halo"), ctx))
    finally:
        monkeypatch.setattr(main, "_tg_inbound_queue", old_queue)

    assert "Antrian penuh" in bot.messages[-1]["text"]


def test_telegram_processing_timeout_sends_fallback(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_TELEGRAM_RESPONSE_TIMEOUT_S", 1, raising=False)
    monkeypatch.setattr(main.chat_history, "add_message", lambda *args, **kwargs: 1)
    monkeypatch.setattr(main.auth_db, "get_user", lambda username: {"master_name": "Master"})

    def _slow_graph(*args, **kwargs):
        import time

        time.sleep(2)
        return "late"

    monkeypatch.setattr(main, "process_chat_with_graph", _slow_graph)
    bot = _FakeBot()

    asyncio.run(
        main._process_telegram_chat_payload(
            {"chat_id": "12345", "text": "slow"},
            bot,
        )
    )

    assert "terlalu lama" in bot.messages[-1]["text"]


def test_telegram_command_center_basic_commands(monkeypatch):
    monkeypatch.setattr(main.settings, "TELEGRAM_CHAT_ID", "12345", raising=False)
    monkeypatch.setattr(main.intelligence_db, "get_failed_notification_summary", lambda: {"pending": 1, "sent": 2, "dead": 3, "total": 6})
    monkeypatch.setattr(main, "_build_system_status_backup_payload", lambda: {"last_backup_status": "completed", "last_backup_at": "now"})
    monkeypatch.setattr(main.finance_db, "is_snapshot_stale", lambda threshold, username="Pantronux": False)
    monkeypatch.setattr(main.finance_db, "get_all_sentinel_stocks", lambda sort_by="latest", category=None, username="Pantronux": [{"stock_code": "MDKA", "current_price_per_share": 2550, "projected_roi_1m": 1.5, "conclusion": "HOLD"}])
    monkeypatch.setattr(main.auth_db, "get_user", lambda username: {"master_name": "Master"})
    monkeypatch.setattr(main.intelligence_db, "get_briefings", lambda limit=1, username="Pantronux": [{"raw_json_data": {"date": "2026-05-22", "status_pagi": "OK"}}])
    bot = _FakeBot()
    ctx = _FakeContext(bot=bot)

    async def _run():
        for command in ["/help", "/ping", "/status", "/queue", "/sentinel", "/briefing"]:
            await main.handle_telegram_command(_FakeUpdate(chat_id="12345", text=command), ctx)

    asyncio.run(_run())

    texts = "\n".join(msg["text"] for msg in bot.messages)
    assert "Command Center" in texts
    assert "Pong" in texts
    assert "Kuro System Status" in texts
    assert "Telegram Queue" in texts
    assert "Market Sentinel" in texts
    assert "LAPORAN INTELJEN HARIAN" in texts
