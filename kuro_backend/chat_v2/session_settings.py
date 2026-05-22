"""Chat V2 session settings persistence."""
from __future__ import annotations

from typing import Optional

from kuro_backend import chat_history
from kuro_backend.chat_v2.schemas import ChatSessionSettings


class ChatSettingsRepository:
    def get(self, *, chat_id: str, username: str) -> Optional[ChatSessionSettings]:
        raw = chat_history.get_session_settings(chat_id, username)
        if raw is None:
            return None
        return ChatSessionSettings(**raw)

    def save(
        self,
        *,
        chat_id: str,
        username: str,
        settings: ChatSessionSettings,
    ) -> ChatSessionSettings:
        stored = settings.model_dump()
        ok = chat_history.update_session_fields(chat_id, username, **stored)
        if not ok:
            raise PermissionError("Chat session not found or not owned by user")
        return settings
