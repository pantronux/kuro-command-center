"""Outbound notifier for Telegram API V2."""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional

from kuro_backend.telegram_v2.queue import TelegramV2QueueStore
from kuro_backend.telegram_v2.schemas import TelegramOutboundMessage


TelegramSender = Callable[[str, str, Dict[str, Any]], bool]


class TelegramV2Notifier:
    def __init__(
        self,
        *,
        queue: Optional[TelegramV2QueueStore] = None,
        sender: Optional[TelegramSender] = None,
        max_attempts: int = 3,
        retry_delay_seconds: int = 60,
    ) -> None:
        self.queue = queue or TelegramV2QueueStore()
        self.sender = sender or self._default_sender
        self.max_attempts = max(1, int(max_attempts or 3))
        self.retry_delay_seconds = max(1, int(retry_delay_seconds or 60))

    def enqueue_text(
        self,
        *,
        username: str,
        chat_id: str,
        text: str,
        channel: str = "telegram",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TelegramOutboundMessage:
        return self.queue.enqueue(
            username=username,
            chat_id=chat_id,
            channel=channel,
            payload={"text": text, "metadata": metadata or {}},
        )

    def send_message(self, message_id: str) -> TelegramOutboundMessage:
        message = self.queue.get_message(message_id)
        if message is None:
            raise KeyError("telegram outbound message not found")
        text = str(message.payload_json.get("text") or "")
        try:
            ok = bool(self.sender(message.chat_id, text, message.payload_json))
        except Exception as exc:
            ok = False
            error = str(exc)
        else:
            error = "" if ok else "telegram send failed"
        if ok:
            sent = self.queue.mark_sent(message.message_id)
            if sent is None:
                raise RuntimeError("telegram outbound message disappeared after send")
            return sent
        failed = self.queue.mark_failure(
            message.message_id,
            error=error,
            max_attempts=self.max_attempts,
            retry_delay_seconds=self.retry_delay_seconds,
        )
        if failed is None:
            raise RuntimeError("telegram outbound message disappeared after failure")
        return failed

    def retry_message(self, message_id: str) -> TelegramOutboundMessage:
        message = self.queue.reset_for_retry(message_id)
        if message is None:
            raise KeyError("telegram outbound message not found")
        return self.send_message(message.message_id)

    def _default_sender(self, chat_id: str, text: str, payload: Dict[str, Any]) -> bool:
        from kuro_backend import telegram_notifier

        _ = payload
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop and running_loop.is_running():
            asyncio.create_task(telegram_notifier.send_message_with_retry(text, chat_id=chat_id))
            return True
        return asyncio.run(telegram_notifier.send_message_with_retry(text, chat_id=chat_id))
