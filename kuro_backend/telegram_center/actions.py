"""Confirmation-gated Telegram cockpit actions."""

from __future__ import annotations

import json
import time
import uuid
from typing import Callable

from kuro_backend import intelligence_db
from kuro_backend.config import settings
from .models import PendingAction

_PENDING_ACTIONS: dict[str, PendingAction] = {}


def reset_pending_actions_for_tests() -> None:
    _PENDING_ACTIONS.clear()


def _ttl_seconds() -> int:
    return max(30, int(getattr(settings, "KURO_TELEGRAM_CONFIRM_TTL_S", 300)))


def create_pending_action(
    *,
    chat_id: str,
    username: str,
    action: str,
    summary: str,
    confirm_label: str,
    execute: Callable[[], str],
) -> PendingAction:
    token = uuid.uuid4().hex[:16]
    pending = PendingAction(
        token=token,
        chat_id=str(chat_id),
        username=username,
        action=action,
        summary=summary,
        confirm_label=confirm_label,
        execute=execute,
        expires_at=time.time() + _ttl_seconds(),
        trace_id=f"telegram_action_{uuid.uuid4().hex[:12]}",
    )
    _PENDING_ACTIONS[token] = pending
    return pending


def cancel_pending_action(token: str, chat_id: str) -> bool:
    pending = _PENDING_ACTIONS.get(token)
    if not pending or pending.chat_id != str(chat_id):
        return False
    _PENDING_ACTIONS.pop(token, None)
    return True


def execute_pending_action(token: str, chat_id: str) -> tuple[bool, str]:
    pending = _PENDING_ACTIONS.pop(token, None)
    if not pending or pending.chat_id != str(chat_id):
        return False, "Action token tidak valid atau sudah dipakai."
    if pending.expires_at < time.time():
        _audit(pending, "expired", "confirmation token expired")
        return False, "Action token sudah kedaluwarsa. Ulangi dari menu Actions."

    try:
        result = pending.execute()
        _audit(pending, "success", result)
        return True, result
    except Exception as exc:
        _audit(pending, "failed", str(exc))
        return False, f"Action gagal: {exc}"


def _audit(pending: PendingAction, status: str, result: str) -> None:
    details = {
        "telegram_chat_id": pending.chat_id,
        "username": pending.username,
        "action": pending.action,
        "status": status,
        "result": result,
    }
    try:
        intelligence_db.add_audit_trail(
            action=f"telegram:{pending.action}:{status}",
            details=json.dumps(details, ensure_ascii=False),
            trace_id=pending.trace_id,
        )
    except Exception:
        pass


def make_run_sentinel_action(username: str) -> tuple[str, str, Callable[[], str]]:
    summary = "Run Market Sentinel sekarang: update harga lalu jalankan triangulation scan."
    label = "Confirm Sentinel"

    def _execute() -> str:
        from kuro_backend import market_sentinel, price_ticker_worker

        price_ticker_worker.run_price_update(username=username)
        ok = market_sentinel.run_triangulation_scan(username=username)
        return f"Market Sentinel selesai. status={'success' if ok else 'failed'}"

    return summary, label, _execute


def make_run_backup_action(username: str) -> tuple[str, str, Callable[[], str]]:
    summary = "Run manual backup sekarang untuk database dan artefak runtime penting."
    label = "Confirm Backup"

    def _execute() -> str:
        from kuro_backend import backup_manager

        result = backup_manager.run_manual_backup("telegram")
        status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
        files = result.get("files_backed_up", 0) if isinstance(result, dict) else 0
        return f"Manual backup selesai. status={status}, files={files}, operator={username}"

    return summary, label, _execute
