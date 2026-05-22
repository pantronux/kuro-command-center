"""Typed schemas for Telegram API V2."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator


OutboundStatus = Literal["pending", "retry", "sent", "dead"]


def telegram_v2_db_path() -> Path:
    configured = os.getenv("KURO_TELEGRAM_V2_DB_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    working_dir = os.getenv("WORKING_DIR", "").strip()
    root = Path(working_dir).expanduser() if working_dir else Path(__file__).resolve().parents[2]
    return root / "kuro_telegram_v2.db"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class TelegramOutboundMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: new_id("tgmsg"))
    username: str
    chat_id: str
    channel: str = "telegram"
    payload_json: Dict[str, Any] = Field(default_factory=dict)
    status: OutboundStatus = "pending"
    attempt_count: int = 0
    next_retry_at: Optional[str] = None
    last_error: str = ""
    created_at: str
    sent_at: Optional[str] = None


class TelegramSenderMapping(BaseModel):
    mapping_id: str = Field(default_factory=lambda: new_id("tgmap"))
    telegram_user_id: str
    username: str
    telegram_chat_id: Optional[str] = None
    display_name: str = ""
    active: bool = True
    created_at: str
    updated_at: str


class TelegramSenderMappingRequest(BaseModel):
    telegram_user_id: str = Field(..., min_length=1, max_length=128)
    username: str = Field(..., min_length=1, max_length=128)
    telegram_chat_id: Optional[str] = Field(default=None, max_length=128)
    display_name: str = ""
    active: bool = True

    @field_validator("telegram_user_id", "username", "telegram_chat_id", "display_name")
    @classmethod
    def _clean(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return str(value or "").strip()[:128]


class TelegramInboundMessage(BaseModel):
    update_id: Optional[int] = None
    message_id: Optional[int] = None
    chat_id: str
    sender_id: str
    sender_username: str = ""
    text: str
    raw_update: Dict[str, Any] = Field(default_factory=dict)


class TelegramCommandResult(BaseModel):
    command: str
    handled: bool = True
    response_text: str = ""
    action: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)


class TelegramWebhookResult(BaseModel):
    accepted: bool = True
    username: str
    chat_id: str
    command: TelegramCommandResult
    queued_message_id: Optional[str] = None


class TelegramHealth(BaseModel):
    enabled: bool
    webhook_secret_configured: bool
    token_configured: bool
    queue_counts: Dict[str, int] = Field(default_factory=dict)
    mapping_count: int = 0
