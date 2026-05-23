"""Interactive Telegram cockpit service.

This module owns Telegram inbound routing, callbacks, command registry,
confirmation-gated actions, and polling lifecycle. ``main.py`` should delegate
to this module instead of carrying bot logic inline.
"""

from __future__ import annotations

import asyncio
import atexit
import fcntl
import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Optional

import psutil
from telegram import Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from kuro_backend import chat_history, finance_db, intelligence_db
from kuro_backend.config import settings
from kuro_backend.langgraph_core import process_chat_with_graph
from kuro_backend.telegram_notifier import split_text_for_telegram
from . import actions, auth, notifications, renderers
from .models import CommandSpec, Panel

logger = logging.getLogger(__name__)
logger.propagate = False

rate_buckets: dict[str, dict] = defaultdict(
    lambda: {
        "tokens": float(getattr(settings, "KURO_TELEGRAM_RATE_LIMIT_PER_MIN", 10)),
        "last_refill": time.time(),
    }
)
inbound_queue: asyncio.Queue = asyncio.Queue(
    maxsize=int(getattr(settings, "KURO_TELEGRAM_QUEUE_MAXSIZE", 50))
)
polling_shutdown = threading.Event()
selected_persona_by_chat: dict[str, str] = {}


def shutdown() -> None:
    polling_shutdown.set()


def reset_runtime_for_tests() -> None:
    rate_buckets.clear()
    selected_persona_by_chat.clear()
    polling_shutdown.clear()
    actions.reset_pending_actions_for_tests()
    notifications.reset_digest_for_tests()
    while not inbound_queue.empty():
        inbound_queue.get_nowait()
        inbound_queue.task_done()


def check_rate_limit(chat_id: str, limit_per_min: int) -> bool:
    bucket = rate_buckets[str(chat_id)]
    now = time.time()
    elapsed = now - float(bucket.get("last_refill", now))
    refill = elapsed * (float(limit_per_min) / 60.0)
    bucket["tokens"] = min(
        float(limit_per_min), float(bucket.get("tokens", 0.0)) + refill
    )
    bucket["last_refill"] = now
    if float(bucket["tokens"]) >= 1.0:
        bucket["tokens"] -= 1.0
        return True
    return False


def command_name(text: str) -> str:
    first = (text or "").strip().split(maxsplit=1)[0].lower()
    if "@" in first:
        first = first.split("@", 1)[0]
    return first


def queue_summary() -> Dict[str, int]:
    dlq = intelligence_db.get_failed_notification_summary()
    return {
        "inbound_size": int(inbound_queue.qsize()),
        "inbound_maxsize": int(inbound_queue.maxsize),
        "dlq_pending": int(dlq.get("pending", 0)),
        "dlq_sent": int(dlq.get("sent", 0)),
        "dlq_dead": int(dlq.get("dead", 0)),
        "dlq_total": int(dlq.get("total", 0)),
    }


def system_status_payload() -> Dict[str, Any]:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    backup = backup_summary()
    q = queue_summary()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0),
        "ram_used_gb": round(mem.used / (1024**3), 1),
        "ram_total_gb": round(mem.total / (1024**3), 1),
        "ram_percent": mem.percent,
        "disk_used_gb": round(disk.used / (1024**3), 1),
        "disk_total_gb": round(disk.total / (1024**3), 1),
        "disk_percent": disk.percent,
        "backup_status": backup.get("last_backup_status", "unknown"),
        "backup_at": backup.get("last_backup_at", "-"),
        **q,
    }


def backup_summary() -> Dict[str, Any]:
    try:
        last_backup = intelligence_db.get_last_backup_status()
    except Exception:
        last_backup = None
    if not last_backup:
        return {"last_backup_status": "unknown", "last_backup_at": "-"}
    return {
        "last_backup_status": last_backup.get("status", "unknown"),
        "last_backup_at": last_backup.get("completed_at") or last_backup.get("started_at") or "-",
        "backup_type": last_backup.get("backup_type", "-"),
    }


async def _home_panel(chat_id: str, context: Any) -> Panel:
    _, display_name = auth.admin_profile()
    return renderers.home_panel(display_name)


async def _help_panel(chat_id: str, context: Any) -> Panel:
    commands = [(spec.name, spec.description) for spec in command_registry().values()]
    return renderers.help_panel(commands)


async def _ping_panel(chat_id: str, context: Any) -> Panel:
    return renderers.ping_panel(queue_summary())


async def _queue_panel(chat_id: str, context: Any) -> Panel:
    return renderers.queue_panel(queue_summary())


async def _status_panel(chat_id: str, context: Any) -> Panel:
    return renderers.status_panel(system_status_payload())


async def _sentinel_panel(chat_id: str, context: Any) -> Panel:
    username, _ = auth.admin_profile()
    stale = finance_db.is_snapshot_stale(
        int(getattr(settings, "KURO_SENTINEL_STALE_THRESHOLD_MIN", 15)),
        username=username,
    )
    stocks = finance_db.get_all_sentinel_stocks(sort_by="roi_1m", username=username)[:5]
    return renderers.sentinel_panel(stale, stocks)


async def _briefing_panel(chat_id: str, context: Any) -> Panel:
    username, display_name = auth.admin_profile()
    briefings = intelligence_db.get_briefings(limit=1, username=username)
    if not briefings:
        return renderers.briefing_panel(
            "Belum ada briefing tersimpan. Jalankan riset harian dari dashboard atau tunggu scheduler berikutnya."
        )
    from kuro_backend.intelligence_engine import format_telegram_message

    briefing = briefings[0].get("raw_json_data") or {}
    return renderers.briefing_panel(format_telegram_message(briefing, display_name=display_name))


async def _chat_panel(chat_id: str, context: Any) -> Panel:
    return renderers.chat_panel(selected_persona_by_chat.get(str(chat_id), "auto"))


async def _persona_panel(chat_id: str, context: Any) -> Panel:
    return renderers.chat_panel(selected_persona_by_chat.get(str(chat_id), "auto"))


async def _actions_panel(chat_id: str, context: Any) -> Panel:
    return renderers.actions_panel()


async def _run_sentinel_confirm_panel(chat_id: str, context: Any) -> Panel:
    username, _ = auth.admin_profile()
    summary, label, execute = actions.make_run_sentinel_action(username)
    pending = actions.create_pending_action(
        chat_id=chat_id,
        username=username,
        action="run_sentinel",
        summary=summary,
        confirm_label=label,
        execute=execute,
    )
    return renderers.confirmation_panel(summary, pending.token, label)


async def _run_backup_confirm_panel(chat_id: str, context: Any) -> Panel:
    username, _ = auth.admin_profile()
    summary, label, execute = actions.make_run_backup_action(username)
    pending = actions.create_pending_action(
        chat_id=chat_id,
        username=username,
        action="run_backup",
        summary=summary,
        confirm_label=label,
        execute=execute,
    )
    return renderers.confirmation_panel(summary, pending.token, label)


_COMMANDS: dict[str, CommandSpec] | None = None


def command_registry() -> dict[str, CommandSpec]:
    global _COMMANDS
    if _COMMANDS is None:
        specs = [
            CommandSpec("/home", "open interactive cockpit", _home_panel, aliases=("/start",)),
            CommandSpec("/help", "show command registry", _help_panel),
            CommandSpec("/ping", "check bot and queue health", _ping_panel),
            CommandSpec("/status", "show system, backup, and Telegram status", _status_panel),
            CommandSpec("/queue", "show inbound queue and DLQ health", _queue_panel),
            CommandSpec("/sentinel", "show Market Sentinel panel", _sentinel_panel),
            CommandSpec("/briefing", "show latest intelligence briefing", _briefing_panel),
            CommandSpec("/chat", "show chat/persona panel", _chat_panel),
            CommandSpec("/persona", "choose active Telegram persona", _persona_panel),
            CommandSpec("/actions", "show confirmation-gated actions", _actions_panel),
            CommandSpec("/run_sentinel", "confirm and run Market Sentinel", _run_sentinel_confirm_panel, mutating=True),
            CommandSpec("/run_backup", "confirm and run manual backup", _run_backup_confirm_panel, mutating=True),
        ]
        _COMMANDS = {}
        for spec in specs:
            _COMMANDS[spec.name] = spec
            for alias in spec.aliases:
                _COMMANDS[alias] = spec
    return _COMMANDS


def build_operational_digest_text() -> str:
    status = system_status_payload()
    username, _ = auth.admin_profile()
    stale = finance_db.is_snapshot_stale(
        int(getattr(settings, "KURO_SENTINEL_STALE_THRESHOLD_MIN", 15)),
        username=username,
    )
    stocks = finance_db.get_all_sentinel_stocks(sort_by="roi_1m", username=username)[:3]
    briefings = intelligence_db.get_briefings(limit=1, username=username)
    briefing_date = briefings[0].get("date") if briefings else "none"
    buffered = notifications.flush_digest()
    lines = [
        "Kuro Operational Digest",
        f"System: CPU {status['cpu_percent']}%, RAM {status['ram_percent']}%, Disk {status['disk_percent']}%",
        f"Backup: {status.get('backup_status', 'unknown')} at {status.get('backup_at', '-')}",
        f"Telegram: inbound {status['inbound_size']}/{status['inbound_maxsize']}, DLQ pending {status['dlq_pending']}",
        f"Market Sentinel: {'STALE' if stale else 'fresh'}",
        f"Latest briefing: {briefing_date}",
    ]
    if stocks:
        lines.append("Top market watch:")
        for stock in stocks:
            lines.append(
                f"- {stock.get('stock_code', '-')}: ROI 1M {stock.get('projected_roi_1m', 0)}%, {stock.get('conclusion', 'HOLD')}"
            )
    if buffered and "No buffered events." not in buffered:
        lines.extend(["", buffered])
    return "\n".join(lines)


def send_digest_job() -> None:
    if not bool(getattr(settings, "KURO_TELEGRAM_DIGEST_ENABLED", True)):
        return
    from kuro_backend import telegram_notifier

    asyncio.run(telegram_notifier.send_message_with_retry(build_operational_digest_text()))


def resolve_command(text: str) -> CommandSpec:
    return command_registry().get(command_name(text), command_registry()["/help"])


async def send_panel(bot, chat_id: str, panel: Panel) -> None:
    kwargs = {}
    if panel.reply_markup is not None:
        kwargs["reply_markup"] = panel.reply_markup
    if panel.parse_mode is not None:
        kwargs["parse_mode"] = panel.parse_mode
    await bot.send_message(chat_id=chat_id, text=panel.text, **kwargs)


async def edit_or_send_panel(query, bot, chat_id: str, panel: Panel) -> None:
    kwargs = {}
    if panel.reply_markup is not None:
        kwargs["reply_markup"] = panel.reply_markup
    if panel.parse_mode is not None:
        kwargs["parse_mode"] = panel.parse_mode
    if query is not None and hasattr(query, "edit_message_text"):
        await query.edit_message_text(text=panel.text, **kwargs)
    else:
        await bot.send_message(chat_id=chat_id, text=panel.text, **kwargs)


async def send_long_message(bot, chat_id: str, text: str) -> None:
    chunks = split_text_for_telegram(text or "", chunk_size=3900)
    total = len(chunks)
    for idx, chunk in enumerate(chunks or [""], start=1):
        if total > 1:
            chunk = f"Part {idx}/{total}\n\n{chunk}"
        await bot.send_message(chat_id=chat_id, text=chunk)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_command(update, context)


async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not auth.is_authorized_chat(chat_id):
        await context.bot.send_message(
            chat_id=chat_id,
            text="I apologize, but I am only authorized to serve Pantronux.",
        )
        logger.warning("Unauthorized Telegram command attempt by chat_id: %s", chat_id)
        return

    text = (getattr(update.message, "text", "") or "/home").strip()
    spec = resolve_command(text)
    panel = await spec.handler(chat_id, context)
    await send_panel(context.bot, chat_id, panel)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = str(query.message.chat_id)
    if hasattr(query, "answer"):
        await query.answer()
    if not auth.is_authorized_chat(chat_id):
        logger.warning("Unauthorized Telegram callback attempt by chat_id: %s", chat_id)
        return

    data = str(getattr(query, "data", "") or "")
    if data == "home":
        panel = await _home_panel(chat_id, context)
    elif data.startswith("panel:"):
        panel = await _panel_from_callback(data.split(":", 1)[1], chat_id, context)
    elif data.startswith("persona:"):
        persona = data.split(":", 1)[1]
        selected_persona_by_chat[chat_id] = persona
        panel = renderers.chat_panel(persona)
    elif data.startswith("action:"):
        panel = await _panel_from_callback(data.split(":", 1)[1], chat_id, context)
    elif data.startswith("confirm:"):
        ok, message = await asyncio.to_thread(
            actions.execute_pending_action,
            data.split(":", 1)[1],
            chat_id,
        )
        panel = renderers.action_result_panel("Action Completed" if ok else "Action Failed", message)
    elif data.startswith("cancel:"):
        ok = actions.cancel_pending_action(data.split(":", 1)[1], chat_id)
        panel = renderers.action_result_panel(
            "Action Cancelled" if ok else "Action Not Found",
            "Aksi dibatalkan." if ok else "Token tidak valid atau sudah kedaluwarsa.",
        )
    else:
        panel = await _home_panel(chat_id, context)
    await edit_or_send_panel(query, context.bot, chat_id, panel)


async def _panel_from_callback(target: str, chat_id: str, context: Any) -> Panel:
    command_map = {
        "home": "/home",
        "help": "/help",
        "ping": "/ping",
        "status": "/status",
        "queue": "/queue",
        "sentinel": "/sentinel",
        "briefing": "/briefing",
        "chat": "/chat",
        "actions": "/actions",
        "run_sentinel": "/run_sentinel",
        "run_backup": "/run_backup",
    }
    if target == "actions":
        return await _actions_panel(chat_id, context)
    spec = command_registry().get(command_map.get(target, "/home"), command_registry()["/home"])
    return await spec.handler(chat_id, context)


async def process_chat_payload(payload: Dict[str, Any], bot) -> None:
    chat_id = str(payload.get("chat_id") or "")
    message_text = str(payload.get("text") or "").strip()
    if not chat_id or not message_text:
        return

    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    trace_id = str(payload.get("trace_id") or f"telegram_chat_{uuid.uuid4().hex}")
    short_trace = trace_id[-8:]
    try:
        username, master_name = auth.admin_profile()
        persona = str(
            payload.get("persona")
            or selected_persona_by_chat.get(chat_id)
            or route_persona(message_text)
        )
        request_id = str(payload.get("request_id") or f"telegram_{uuid.uuid4().hex}")
        chat_history.add_message(
            "telegram",
            "user",
            message_text,
            persona=persona,
            request_id=request_id,
            username=username,
        )
        response_text = await asyncio.wait_for(
            asyncio.to_thread(
                process_chat_with_graph,
                message_text,
                persona_override=persona,
                approval_scope=f"telegram:{chat_id}:{persona}",
                trace_id=trace_id,
                master_name=master_name,
                username=username,
            ),
            timeout=int(getattr(settings, "KURO_TELEGRAM_RESPONSE_TIMEOUT_S", 180)),
        )
        chat_history.add_message(
            "telegram",
            "assistant",
            response_text,
            persona=persona,
            request_id=request_id,
            username=username,
        )
        await send_long_message(bot, chat_id, response_text)
    except asyncio.TimeoutError:
        logger.warning("[TELEGRAM] chat processing timed out trace=%s", trace_id)
        await bot.send_message(
            chat_id=chat_id,
            text=f"Kuro butuh waktu terlalu lama untuk menjawab. Trace: {short_trace}",
        )
    except Exception as exc:
        logger.exception("Error sending response to Telegram trace=%s: %s", trace_id, exc)
        await bot.send_message(
            chat_id=chat_id,
            text=f"My apologies, Master - response delivery failed. Trace: {short_trace}",
        )


async def inbound_queue_worker(bot, max_items: Optional[int] = None) -> None:
    processed = 0
    while not polling_shutdown.is_set():
        if max_items is not None and processed >= max_items:
            return
        try:
            if max_items is None:
                payload = await inbound_queue.get()
            else:
                payload = await asyncio.wait_for(inbound_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return
        except asyncio.CancelledError:
            raise
        try:
            await process_chat_payload(payload, bot)
        except Exception as exc:
            logger.exception("[TELEGRAM] inbound queue worker failed: %s", exc)
        finally:
            inbound_queue.task_done()
            processed += 1


async def post_init(application):
    application.create_task(inbound_queue_worker(application.bot))


def schedule_chat_payload(payload: Dict[str, Any], context: ContextTypes.DEFAULT_TYPE) -> None:
    coro = process_chat_payload(payload, context.bot)
    application = getattr(context, "application", None)
    if application and hasattr(application, "create_task"):
        application.create_task(coro)
    else:
        asyncio.create_task(coro)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not auth.is_authorized_chat(chat_id):
        await context.bot.send_message(
            chat_id=chat_id,
            text="I apologize, but I am only authorized to serve Pantronux.",
        )
        logger.warning("Unauthorized Telegram message attempt by chat_id: %s", chat_id)
        return

    text = (getattr(update.message, "text", "") or "").strip()
    if not text:
        return

    payload = {
        "chat_id": chat_id,
        "text": text,
        "received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "request_id": f"telegram_{uuid.uuid4().hex}",
        "trace_id": f"telegram_chat_{uuid.uuid4().hex}",
    }
    if not check_rate_limit(chat_id, int(getattr(settings, "KURO_TELEGRAM_RATE_LIMIT_PER_MIN", 10))):
        try:
            inbound_queue.put_nowait(payload)
            await context.bot.send_message(
                chat_id=chat_id,
                text="Queued. Kuro akan membalas setelah giliran ini diproses.",
            )
        except asyncio.QueueFull:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Antrian penuh. Coba lagi dalam beberapa menit.",
            )
        return

    persona = selected_persona_by_chat.get(chat_id, "auto")
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Received. Processing with persona: {persona}.",
    )
    schedule_chat_payload(payload, context)


def route_persona(message_text: str) -> str:
    text = (message_text or "").lower()
    technical_keywords = [
        "proxmox",
        "server",
        "docker",
        "kubernetes",
        "code",
        "python",
        "error",
        "bug",
        "api",
        "database",
        "sql",
        "log",
        "linux",
        "deploy",
        "security",
        "iso",
        "audit",
        "openclaw",
        "memory",
        "websocket",
        "revision",
        "ci",
        "cd",
    ]
    casual_keywords = [
        "gym",
        "musik",
        "lagu",
        "hindia",
        "hsr",
        "honkai",
        "capek",
        "semangat",
        "mood",
        "curhat",
        "istirahat",
        "ngobrol",
        "santai",
        "hari ini",
    ]
    if any(keyword in text for keyword in technical_keywords):
        return "tactical"
    if any(keyword in text for keyword in casual_keywords):
        return "chill"
    return "tactical"


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning("Telegram network error: %s", error)
        return
    logger.error("Telegram update %s caused error: %s", update, error, exc_info=error)


def run_bot_with_recovery():
    max_retries = 5
    retry_delay = 5
    for attempt in range(max_retries):
        if polling_shutdown.is_set():
            logger.info("Telegram polling shutdown flag set; exiting polling loop.")
            break
        try:
            logger.info("Starting Telegram cockpit polling... (Attempt %s/%s)", attempt + 1, max_retries)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            app = (
                ApplicationBuilder()
                .token(settings.TELEGRAM_TOKEN)
                .post_init(post_init)
                .build()
            )
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler(_command_names_for_handler(), handle_command))
            app.add_handler(CallbackQueryHandler(handle_callback))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
            app.add_error_handler(error_handler)
            app.run_polling(
                drop_pending_updates=bool(
                    getattr(settings, "KURO_TELEGRAM_DROP_PENDING_UPDATES", False)
                )
            )
        except (NetworkError, TimedOut) as exc:
            logger.warning("Network error during Telegram polling: %s", exc)
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                raise
        except KeyboardInterrupt:
            logger.info("Received Telegram shutdown signal.")
            break
        except BaseException as exc:
            logger.exception("Telegram polling exited with %s: %s", type(exc).__name__, exc)
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                raise


def _command_names_for_handler() -> list[str]:
    names = sorted({name.lstrip("/") for name in command_registry().keys()})
    return [name for name in names if name != "start"]


def acquire_bot_lock() -> bool:
    lock_path = Path(settings.WORKING_DIR) / ".kuro_telegram.lock"
    try:
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        atexit.register(lambda: lock_path.exists() and lock_path.unlink())
        return True
    except (BlockingIOError, PermissionError) as exc:
        logger.critical(
            "Another Kuro Telegram bot is already running or lock file is inaccessible: %s. "
            "Kill the old process first. Exiting.",
            exc,
        )
        return False
