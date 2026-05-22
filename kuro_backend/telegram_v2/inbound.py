"""Inbound webhook parsing and dispatch for Telegram API V2."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException

from kuro_backend.telegram_v2.commands import TelegramV2CommandRouter
from kuro_backend.telegram_v2.notifier import TelegramV2Notifier
from kuro_backend.telegram_v2.queue import TelegramV2QueueStore
from kuro_backend.telegram_v2.schemas import TelegramInboundMessage, TelegramWebhookResult


class TelegramV2InboundProcessor:
    def __init__(
        self,
        *,
        queue: Optional[TelegramV2QueueStore] = None,
        command_router: Optional[TelegramV2CommandRouter] = None,
        notifier: Optional[TelegramV2Notifier] = None,
        send_responses: bool = False,
    ) -> None:
        self.queue = queue or TelegramV2QueueStore()
        self.command_router = command_router or TelegramV2CommandRouter()
        self.notifier = notifier or TelegramV2Notifier(queue=self.queue)
        self.send_responses = send_responses

    def parse_update(self, payload: Dict[str, Any]) -> Optional[TelegramInboundMessage]:
        message = payload.get("message") or payload.get("edited_message") or {}
        if not isinstance(message, dict):
            return None
        text = str(message.get("text") or "").strip()
        if not text:
            return None
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        sender = message.get("from") if isinstance(message.get("from"), dict) else {}
        chat_id = str(chat.get("id") or "")
        sender_id = str(sender.get("id") or "")
        if not chat_id or not sender_id:
            return None
        return TelegramInboundMessage(
            update_id=payload.get("update_id"),
            message_id=message.get("message_id"),
            chat_id=chat_id,
            sender_id=sender_id,
            sender_username=str(sender.get("username") or ""),
            text=text,
            raw_update=payload,
        )

    def handle_webhook(self, payload: Dict[str, Any]) -> TelegramWebhookResult:
        inbound = self.parse_update(payload)
        if inbound is None:
            raise HTTPException(status_code=400, detail="Unsupported Telegram update")
        mapping = self.queue.get_mapping(inbound.sender_id)
        if mapping is None or not mapping.active:
            raise HTTPException(status_code=403, detail="Unknown Telegram sender")
        if mapping.telegram_chat_id and mapping.telegram_chat_id != inbound.chat_id:
            raise HTTPException(status_code=403, detail="Unknown Telegram chat")
        command = self.command_router.handle(
            text=inbound.text,
            username=mapping.username,
            chat_id=inbound.chat_id,
            sender_id=inbound.sender_id,
        )
        outbound = self.notifier.enqueue_text(
            username=mapping.username,
            chat_id=inbound.chat_id,
            text=command.response_text,
            metadata={
                "command": command.command,
                "action": command.action,
                "telegram_message_id": inbound.message_id,
            },
        )
        sent_message_id = outbound.message_id
        if self.send_responses:
            sent = self.notifier.send_message(outbound.message_id)
            sent_message_id = sent.message_id
        return TelegramWebhookResult(
            username=mapping.username,
            chat_id=inbound.chat_id,
            command=command,
            queued_message_id=sent_message_id,
        )
