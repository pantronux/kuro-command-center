"""DLQ helpers for Telegram API V2."""
from __future__ import annotations

from typing import List, Optional

from kuro_backend.telegram_v2.notifier import TelegramV2Notifier
from kuro_backend.telegram_v2.queue import TelegramV2QueueStore
from kuro_backend.telegram_v2.schemas import TelegramOutboundMessage


class TelegramV2DLQ:
    def __init__(
        self,
        *,
        queue: Optional[TelegramV2QueueStore] = None,
        notifier: Optional[TelegramV2Notifier] = None,
    ) -> None:
        self.queue = queue or TelegramV2QueueStore()
        self.notifier = notifier or TelegramV2Notifier(queue=self.queue)

    def list_dead(self, *, limit: int = 100) -> List[TelegramOutboundMessage]:
        return self.queue.list_messages(status="dead", limit=limit)

    def retry(self, message_id: str) -> TelegramOutboundMessage:
        return self.notifier.retry_message(message_id)
