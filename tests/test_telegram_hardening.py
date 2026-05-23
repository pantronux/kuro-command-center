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
from kuro_backend.telegram_center import actions as telegram_actions
from kuro_backend.telegram_center import notifications as telegram_notifications
from kuro_backend.telegram_center import service as telegram_service


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
    def __init__(self, chat_id="12345", text="hello", callback_query=None):
        self.effective_chat = _FakeChat(chat_id)
        self.message = _FakeMessage(text)
        self.callback_query = callback_query


class _FakeBot:
    def __init__(self):
        self.messages = []
        self.actions = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append({"chat_id": str(chat_id), "text": text, **kwargs})

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


class _FakeCallbackMessage:
    def __init__(self, chat_id="12345"):
        self.chat_id = chat_id


class _FakeCallbackQuery:
    def __init__(self, data, chat_id="12345"):
        self.data = data
        self.message = _FakeCallbackMessage(chat_id)
        self.edits = []
        self.answered = False

    async def answer(self):
        self.answered = True

    async def edit_message_text(self, text, **kwargs):
        self.edits.append({"text": text, **kwargs})


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
    telegram_service.reset_runtime_for_tests()
    monkeypatch.setattr(main.settings, "TELEGRAM_CHAT_ID", "12345", raising=False)
    monkeypatch.setattr(telegram_service, "check_rate_limit", lambda chat_id, limit: True)
    monkeypatch.setattr(telegram_service.chat_history, "add_message", lambda *args, **kwargs: 1)
    monkeypatch.setattr(telegram_service, "process_chat_with_graph", lambda *args, **kwargs: "jawaban")
    monkeypatch.setattr(telegram_service.auth, "admin_profile", lambda: ("Pantronux", "Master"))
    bot = _FakeBot()
    app = _InlineApplication()
    ctx = _FakeContext(bot=bot, application=app)

    async def _run():
        await main.handle_message(_FakeUpdate(chat_id="12345", text="halo"), ctx)
        await asyncio.gather(*app.tasks)

    asyncio.run(_run())

    assert bot.messages[0]["text"].startswith("Received")
    assert bot.messages[-1]["text"] == "jawaban"


def test_rate_limited_message_is_processed_by_queue_worker(monkeypatch):
    telegram_service.reset_runtime_for_tests()
    monkeypatch.setattr(main.settings, "TELEGRAM_CHAT_ID", "12345", raising=False)
    monkeypatch.setattr(telegram_service, "check_rate_limit", lambda chat_id, limit: False)
    monkeypatch.setattr(telegram_service.chat_history, "add_message", lambda *args, **kwargs: 1)
    monkeypatch.setattr(telegram_service, "process_chat_with_graph", lambda *args, **kwargs: "queued answer")
    monkeypatch.setattr(telegram_service.auth, "admin_profile", lambda: ("Pantronux", "Master"))
    bot = _FakeBot()
    ctx = _FakeContext(bot=bot)

    async def _run():
        while not telegram_service.inbound_queue.empty():
            telegram_service.inbound_queue.get_nowait()
            telegram_service.inbound_queue.task_done()
        await main.handle_message(_FakeUpdate(chat_id="12345", text="queued"), ctx)
        await main._telegram_inbound_queue_worker(bot, max_items=1)

    asyncio.run(_run())

    assert any("queued" in msg["text"].lower() for msg in bot.messages)
    assert bot.messages[-1]["text"] == "queued answer"


def test_queue_full_returns_fallback(monkeypatch):
    telegram_service.reset_runtime_for_tests()
    monkeypatch.setattr(main.settings, "TELEGRAM_CHAT_ID", "12345", raising=False)
    monkeypatch.setattr(telegram_service, "check_rate_limit", lambda chat_id, limit: False)

    class _FullQueue:
        maxsize = 1

        def put_nowait(self, payload):
            raise asyncio.QueueFull

    old_queue = telegram_service.inbound_queue
    monkeypatch.setattr(telegram_service, "inbound_queue", _FullQueue())
    bot = _FakeBot()
    ctx = _FakeContext(bot=bot)
    try:
        asyncio.run(main.handle_message(_FakeUpdate(chat_id="12345", text="halo"), ctx))
    finally:
        monkeypatch.setattr(telegram_service, "inbound_queue", old_queue)

    assert "Antrian penuh" in bot.messages[-1]["text"]


def test_telegram_processing_timeout_sends_fallback(monkeypatch):
    telegram_service.reset_runtime_for_tests()
    monkeypatch.setattr(main.settings, "KURO_TELEGRAM_RESPONSE_TIMEOUT_S", 1, raising=False)
    monkeypatch.setattr(telegram_service.chat_history, "add_message", lambda *args, **kwargs: 1)
    monkeypatch.setattr(telegram_service.auth, "admin_profile", lambda: ("Pantronux", "Master"))

    def _slow_graph(*args, **kwargs):
        import time

        time.sleep(2)
        return "late"

    monkeypatch.setattr(telegram_service, "process_chat_with_graph", _slow_graph)
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
    assert "Command Registry" in texts
    assert "Kuro Ping" in texts
    assert "Kuro System Status" in texts
    assert "Telegram Queue" in texts
    assert "Market Sentinel" in texts
    assert "LAPORAN INTELJEN HARIAN" in texts


def test_command_registry_resolves_home_and_unknown_to_help():
    assert telegram_service.resolve_command("/home").name == "/home"
    assert telegram_service.resolve_command("/not-real").name == "/help"


def test_home_panel_renders_interactive_buttons(monkeypatch):
    telegram_service.reset_runtime_for_tests()
    monkeypatch.setattr(main.settings, "TELEGRAM_CHAT_ID", "12345", raising=False)
    monkeypatch.setattr(telegram_service.auth, "admin_profile", lambda: ("Pantronux", "Master"))
    bot = _FakeBot()
    ctx = _FakeContext(bot=bot)

    asyncio.run(telegram_service.handle_command(_FakeUpdate(chat_id="12345", text="/home"), ctx))

    assert "Kuro Telegram Cockpit" in bot.messages[-1]["text"]
    assert bot.messages[-1].get("reply_markup") is not None


def test_callback_navigation_renders_status_panel(monkeypatch):
    telegram_service.reset_runtime_for_tests()
    monkeypatch.setattr(main.settings, "TELEGRAM_CHAT_ID", "12345", raising=False)
    monkeypatch.setattr(telegram_service.intelligence_db, "get_failed_notification_summary", lambda: {"pending": 0, "sent": 1, "dead": 2, "total": 3})
    monkeypatch.setattr(telegram_service, "backup_summary", lambda: {"last_backup_status": "completed", "last_backup_at": "now"})
    query = _FakeCallbackQuery("panel:status", chat_id="12345")
    ctx = _FakeContext(bot=_FakeBot())

    asyncio.run(telegram_service.handle_callback(_FakeUpdate(chat_id="12345", callback_query=query), ctx))

    assert query.answered is True
    assert "Kuro System Status" in query.edits[-1]["text"]


def test_persona_callback_updates_chat_payload(monkeypatch):
    telegram_service.reset_runtime_for_tests()
    monkeypatch.setattr(main.settings, "TELEGRAM_CHAT_ID", "12345", raising=False)
    query = _FakeCallbackQuery("persona:auditor", chat_id="12345")
    ctx = _FakeContext(bot=_FakeBot())

    asyncio.run(telegram_service.handle_callback(_FakeUpdate(chat_id="12345", callback_query=query), ctx))

    assert telegram_service.selected_persona_by_chat["12345"] == "auditor"
    assert "Selected persona: auditor" in query.edits[-1]["text"]


def test_mutating_action_requires_confirmation_and_executes(monkeypatch):
    telegram_service.reset_runtime_for_tests()
    monkeypatch.setattr(main.settings, "TELEGRAM_CHAT_ID", "12345", raising=False)
    monkeypatch.setattr(telegram_actions.intelligence_db, "add_audit_trail", lambda **kwargs: None)
    calls = []

    def _fake_action(username):
        return "Run Sentinel?", "Confirm Sentinel", lambda: calls.append(username) or "done"

    monkeypatch.setattr(telegram_actions, "make_run_sentinel_action", _fake_action)
    ctx = _FakeContext(bot=_FakeBot())
    action_query = _FakeCallbackQuery("action:run_sentinel", chat_id="12345")
    asyncio.run(telegram_service.handle_callback(_FakeUpdate(chat_id="12345", callback_query=action_query), ctx))
    token = next(iter(telegram_actions._PENDING_ACTIONS))

    confirm_query = _FakeCallbackQuery(f"confirm:{token}", chat_id="12345")
    asyncio.run(telegram_service.handle_callback(_FakeUpdate(chat_id="12345", callback_query=confirm_query), ctx))

    assert calls == ["Pantronux"]
    assert "Action Completed" in confirm_query.edits[-1]["text"]


def test_expired_and_invalid_confirmation_tokens(monkeypatch):
    telegram_service.reset_runtime_for_tests()
    monkeypatch.setattr(telegram_actions.intelligence_db, "add_audit_trail", lambda **kwargs: None)
    pending = telegram_actions.create_pending_action(
        chat_id="12345",
        username="Pantronux",
        action="test",
        summary="Test",
        confirm_label="Confirm",
        execute=lambda: "done",
    )
    pending.expires_at = 0

    ok, expired = telegram_actions.execute_pending_action(pending.token, "12345")
    bad_ok, invalid = telegram_actions.execute_pending_action("missing", "12345")

    assert ok is False
    assert "kedaluwarsa" in expired
    assert bad_ok is False
    assert "tidak valid" in invalid


def test_send_long_message_adds_part_headers():
    bot = _FakeBot()

    asyncio.run(telegram_service.send_long_message(bot, "12345", "x" * 8000))

    assert len(bot.messages) == 3
    assert bot.messages[0]["text"].startswith("Part 1/3")
    assert bot.messages[-1]["text"].startswith("Part 3/3")


def test_digest_buffers_info_but_sends_critical(monkeypatch):
    telegram_notifications.reset_digest_for_tests()
    monkeypatch.setattr(telegram_notifications.settings, "KURO_TELEGRAM_CRITICAL_INSTANT", True, raising=False)

    assert telegram_notifications.queue_or_send_event("info", "Daily", "normal update") is False
    assert telegram_notifications.queue_or_send_event("critical", "Down", "needs attention") is True
    digest = telegram_notifications.flush_digest()

    assert "Daily" in digest
    assert "Down" not in digest


def test_operational_digest_includes_core_sections(monkeypatch):
    telegram_notifications.reset_digest_for_tests()
    monkeypatch.setattr(telegram_service, "system_status_payload", lambda: {
        "cpu_percent": 1,
        "ram_percent": 2,
        "disk_percent": 3,
        "backup_status": "completed",
        "backup_at": "now",
        "inbound_size": 0,
        "inbound_maxsize": 50,
        "dlq_pending": 0,
    })
    monkeypatch.setattr(telegram_service.auth, "admin_profile", lambda: ("Pantronux", "Master"))
    monkeypatch.setattr(telegram_service.finance_db, "is_snapshot_stale", lambda threshold, username="Pantronux": False)
    monkeypatch.setattr(telegram_service.finance_db, "get_all_sentinel_stocks", lambda sort_by="roi_1m", username="Pantronux": [{"stock_code": "MDKA", "projected_roi_1m": 1.5, "conclusion": "HOLD"}])
    monkeypatch.setattr(telegram_service.intelligence_db, "get_briefings", lambda limit=1, username="Pantronux": [{"date": "2026-05-22"}])
    telegram_notifications.queue_or_send_event("info", "Buffered", "hello")

    digest = telegram_service.build_operational_digest_text()

    assert "Kuro Operational Digest" in digest
    assert "Market Sentinel" in digest
    assert "Latest briefing: 2026-05-22" in digest
    assert "Buffered" in digest
