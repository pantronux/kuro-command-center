"""Webhook security helpers for Telegram API V2."""
from __future__ import annotations

import hmac
import os
from typing import Mapping

from fastapi import HTTPException

from kuro_backend.config import settings


SECRET_HEADERS = (
    "x-telegram-bot-api-secret-token",
    "x-kuro-telegram-secret",
    "x-telegram-webhook-secret",
)


def configured_webhook_secret() -> str:
    return str(
        getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
        or os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    ).strip()


def validate_webhook_secret(headers: Mapping[str, str]) -> None:
    expected = configured_webhook_secret()
    if not expected:
        raise HTTPException(status_code=403, detail="Telegram webhook secret is not configured")
    normalized = {str(key).lower(): str(value) for key, value in dict(headers).items()}
    supplied = ""
    for header in SECRET_HEADERS:
        if normalized.get(header):
            supplied = normalized[header]
            break
    if not supplied:
        authorization = normalized.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")


def token_configured() -> bool:
    return bool(str(getattr(settings, "TELEGRAM_TOKEN", "") or os.getenv("TELEGRAM_TOKEN", "")).strip())
