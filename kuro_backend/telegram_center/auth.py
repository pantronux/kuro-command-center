"""Authorization helpers for Telegram cockpit."""

from __future__ import annotations

import os
from typing import Optional

from kuro_backend import auth_db
from kuro_backend.config import settings


def allowed_chat_ids() -> set[str]:
    raw = str(getattr(settings, "TELEGRAM_CHAT_ID", "") or "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def is_authorized_chat(chat_id: object) -> bool:
    return str(chat_id) in allowed_chat_ids()


def admin_profile() -> tuple[str, str]:
    username = os.getenv("ADMIN_USERNAME", "Pantronux")
    display_name = username
    try:
        user_info: Optional[dict] = auth_db.get_user(username)
        if user_info and user_info.get("master_name"):
            display_name = str(user_info["master_name"])
    except Exception:
        pass
    return username, display_name
