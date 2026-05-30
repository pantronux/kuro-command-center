"""Telegram API V2 bridge tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WORKING_DIR", str(PROJECT_ROOT))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kuro_backend.config import settings
from kuro_backend.telegram_v2.commands import TelegramV2CommandRouter
from kuro_backend.telegram_v2.notifier import TelegramV2Notifier
from kuro_backend.telegram_v2.queue import TelegramV2QueueStore
from kuro_backend.telegram_v2.routes import TelegramV2Service, create_telegram_v2_router
from kuro_backend.telegram_v2.schemas import TelegramSenderMappingRequest


SECRET = "telegram-test-secret"


def _telegram_update(
    text: str,
    *,
    sender_id: str = "42",
    chat_id: str = "-10042",
    username: str = "telegram_user",
) -> Dict[str, Any]:
    return {
        "update_id": 9001,
        "message": {
            "message_id": 77,
            "text": text,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": sender_id, "username": username},
        },
    }


@pytest.fixture
def telegram_stack(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "legacy")
    monkeypatch.setattr(settings, "KURO_TELEGRAM_V2_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", SECRET, raising=False)
    monkeypatch.setenv("KURO_TELEGRAM_V2_DB_PATH", str(tmp_path / "telegram_v2.db"))

    calls: Dict[str, list] = {"sent": [], "market": [], "research": [], "tasks": [], "reminders": []}
    queue = TelegramV2QueueStore(tmp_path / "telegram_v2.db")

    def sender(chat_id: str, text: str, payload: Dict[str, Any]) -> bool:
        calls["sent"].append({"chat_id": chat_id, "text": text, "payload": payload})
        return True

    def chat_handler(*, username: str, chat_id: str, message: str) -> Dict[str, Any]:
        return {"text": f"chat:{username}:{chat_id}:{message}"}

    def market_handler(*, username: str, chat_id: str, symbol: str) -> Dict[str, Any]:
        calls["market"].append({"username": username, "chat_id": chat_id, "symbol": symbol})
        return {"text": f"market:{symbol}", "symbol": symbol}

    def research_handler(*, username: str, chat_id: str, topic: str) -> Dict[str, Any]:
        calls["research"].append({"username": username, "chat_id": chat_id, "topic": topic})
        return {"text": f"research:{topic}", "topic": topic}

    def task_handler(*, username: str, chat_id: str, title: str) -> Dict[str, Any]:
        calls["tasks"].append({"username": username, "chat_id": chat_id, "title": title})
        return {"text": f"task:{title}", "task_id": "task_mock"}

    def reminder_handler(*, username: str, chat_id: str, text: str) -> Dict[str, Any]:
        calls["reminders"].append({"username": username, "chat_id": chat_id, "text": text})
        return {"text": f"reminder:{text}", "reminder_id": "reminder_mock"}

    command_router = TelegramV2CommandRouter(
        chat_handler=chat_handler,
        market_handler=market_handler,
        research_handler=research_handler,
        task_handler=task_handler,
        reminder_handler=reminder_handler,
    )
    notifier = TelegramV2Notifier(queue=queue, sender=sender, max_attempts=2, retry_delay_seconds=5)
    service = TelegramV2Service(
        queue=queue,
        notifier=notifier,
        command_router=command_router,
    )
    return {"queue": queue, "service": service, "calls": calls}


def _client(service: TelegramV2Service, *, admin_allowed: bool = True) -> TestClient:
    def admin_dep():
        if not admin_allowed:
            raise HTTPException(status_code=403, detail="admin required")
        return {"username": "Pantronux"}

    app = FastAPI()
    app.include_router(create_telegram_v2_router(admin_dependency=admin_dep, service=service))
    return TestClient(app)


def _seed_mapping(queue: TelegramV2QueueStore, *, sender_id: str = "42", chat_id: str = "-10042") -> None:
    queue.upsert_mapping(
        TelegramSenderMappingRequest(
            telegram_user_id=sender_id,
            telegram_chat_id=chat_id,
            username="Pantronux",
            display_name="Master",
        )
    )


def _webhook_headers(secret: str = SECRET) -> Dict[str, str]:
    return {"X-Telegram-Bot-Api-Secret-Token": secret}


def test_telegram_v2_disabled_by_default(telegram_stack):
    client = _client(telegram_stack["service"])

    response = client.post(
        "/api/telegram/webhook",
        json=_telegram_update("/help"),
        headers=_webhook_headers(),
    )

    assert response.status_code == 404
    assert "disabled" in response.text.lower()


def test_webhook_rejects_missing_secret(telegram_stack, monkeypatch):
    monkeypatch.setattr(settings, "KURO_TELEGRAM_V2_ENABLED", True, raising=False)
    client = _client(telegram_stack["service"])

    response = client.post("/api/telegram/webhook", json=_telegram_update("/help"))

    assert response.status_code == 403
    assert "secret" in response.text.lower()


def test_unknown_sender_rejected(telegram_stack, monkeypatch):
    monkeypatch.setattr(settings, "KURO_TELEGRAM_V2_ENABLED", True, raising=False)
    client = _client(telegram_stack["service"])

    response = client.post(
        "/api/telegram/webhook",
        json=_telegram_update("/help"),
        headers=_webhook_headers(),
    )

    assert response.status_code == 403
    assert "unknown telegram sender" in response.text.lower()


def test_known_sender_command_parsed_and_queued(telegram_stack, monkeypatch):
    monkeypatch.setattr(settings, "KURO_TELEGRAM_V2_ENABLED", True, raising=False)
    _seed_mapping(telegram_stack["queue"])
    client = _client(telegram_stack["service"])

    response = client.post(
        "/api/telegram/webhook",
        json=_telegram_update("/chat hello Kuro"),
        headers=_webhook_headers(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["username"] == "Pantronux"
    assert data["command"]["command"] == "/chat"
    assert data["command"]["action"] == "chat"
    queued = telegram_stack["queue"].get_message(data["queued_message_id"])
    assert queued is not None
    assert queued.payload_json["text"] == "chat:Pantronux:-10042:hello Kuro"


def test_outbound_retry_scheduled_on_failure(tmp_path):
    queue = TelegramV2QueueStore(tmp_path / "telegram_v2.db")
    notifier = TelegramV2Notifier(
        queue=queue,
        sender=lambda chat_id, text, payload: False,
        max_attempts=3,
        retry_delay_seconds=30,
    )
    message = notifier.enqueue_text(username="Pantronux", chat_id="-10042", text="retry me")

    failed = notifier.send_message(message.message_id)

    assert failed.status == "retry"
    assert failed.attempt_count == 1
    assert failed.next_retry_at
    assert failed.last_error == "telegram send failed"


def test_dlq_after_max_attempts_and_admin_inspect(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "KURO_TELEGRAM_V2_ENABLED", True, raising=False)
    queue = TelegramV2QueueStore(tmp_path / "telegram_v2.db")
    notifier = TelegramV2Notifier(
        queue=queue,
        sender=lambda chat_id, text, payload: False,
        max_attempts=2,
        retry_delay_seconds=1,
    )
    service = TelegramV2Service(queue=queue, notifier=notifier, command_router=TelegramV2CommandRouter())
    message = notifier.enqueue_text(username="Pantronux", chat_id="-10042", text="fail twice")

    notifier.send_message(message.message_id)
    dead = notifier.send_message(message.message_id)
    response = _client(service).get("/api/admin/telegram-v2/dlq")

    assert dead.status == "dead"
    assert dead.attempt_count == 2
    assert response.status_code == 200
    assert response.json()["data"][0]["message_id"] == message.message_id


def test_admin_routes_require_admin(telegram_stack):
    client = _client(telegram_stack["service"], admin_allowed=False)

    assert client.get("/api/admin/telegram-v2/health").status_code == 403
    assert client.get("/api/admin/telegram-v2/dlq").status_code == 403
    assert client.get("/api/admin/telegram-v2/mappings").status_code == 403
    assert client.post(
        "/api/admin/telegram-v2/mappings",
        json={"telegram_user_id": "42", "username": "Pantronux"},
    ).status_code == 403


def test_market_command_uses_mocked_market_v2(telegram_stack, monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "legacy")
    monkeypatch.setattr(settings, "KURO_TELEGRAM_V2_ENABLED", True, raising=False)
    _seed_mapping(telegram_stack["queue"])
    client = _client(telegram_stack["service"])

    response = client.post(
        "/api/telegram/webhook",
        json=_telegram_update("/market BBCA"),
        headers={"Authorization": f"Bearer {SECRET}"},
    )

    assert response.status_code == 200
    assert telegram_stack["calls"]["market"] == [
        {"username": "Pantronux", "chat_id": "-10042", "symbol": "BBCA"}
    ]
    assert response.json()["data"]["command"]["response_text"] == "market:BBCA"


def test_krc_telegram_v2_market_command_disabled_by_default(telegram_stack, monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    monkeypatch.delenv("KURO_KRC_MARKET_ENABLED", raising=False)
    monkeypatch.setattr(settings, "KURO_TELEGRAM_V2_ENABLED", True, raising=False)
    _seed_mapping(telegram_stack["queue"])
    client = _client(telegram_stack["service"])

    response = client.post(
        "/api/telegram/webhook",
        json=_telegram_update("/market BBCA"),
        headers=_webhook_headers(),
    )

    assert response.status_code == 200
    assert telegram_stack["calls"]["market"] == []
    body = response.json()["data"]["command"]
    assert body["action"] == "disabled"
    assert "Market commands are disabled" in body["response_text"]


def test_research_command_uses_mocked_deep_research_v2(telegram_stack, monkeypatch):
    monkeypatch.setattr(settings, "KURO_TELEGRAM_V2_ENABLED", True, raising=False)
    _seed_mapping(telegram_stack["queue"])
    client = _client(telegram_stack["service"])

    response = client.post(
        "/api/telegram/webhook",
        json=_telegram_update("/research sovereign memory"),
        headers=_webhook_headers(),
    )

    assert response.status_code == 200
    assert telegram_stack["calls"]["research"] == [
        {"username": "Pantronux", "chat_id": "-10042", "topic": "sovereign memory"}
    ]
    assert response.json()["data"]["command"]["response_text"] == "research:sovereign memory"


def test_task_and_remind_commands_create_mocked_v2_items(telegram_stack, monkeypatch):
    monkeypatch.setattr(settings, "KURO_TELEGRAM_V2_ENABLED", True, raising=False)
    _seed_mapping(telegram_stack["queue"])
    client = _client(telegram_stack["service"])

    task_response = client.post(
        "/api/telegram/webhook",
        json=_telegram_update("/task write Telegram V2 tests"),
        headers=_webhook_headers(),
    )
    remind_response = client.post(
        "/api/telegram/webhook",
        json=_telegram_update("/remind tomorrow review DLQ"),
        headers=_webhook_headers(),
    )

    assert task_response.status_code == 200
    assert remind_response.status_code == 200
    assert telegram_stack["calls"]["tasks"][0]["title"] == "write Telegram V2 tests"
    assert telegram_stack["calls"]["reminders"][0]["text"] == "tomorrow review DLQ"
