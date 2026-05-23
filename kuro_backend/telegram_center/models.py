"""Shared models for Telegram command cockpit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional


@dataclass(frozen=True)
class Panel:
    text: str
    reply_markup: Any = None
    parse_mode: Optional[str] = None


CommandHandlerFn = Callable[[str, Any], Awaitable[Panel]]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    handler: CommandHandlerFn
    required_role: str = "admin"
    mutating: bool = False
    aliases: tuple[str, ...] = ()


@dataclass
class PendingAction:
    token: str
    chat_id: str
    username: str
    action: str
    summary: str
    confirm_label: str
    execute: Callable[[], str]
    expires_at: float
    trace_id: str
