from __future__ import annotations

import os

from fastapi import HTTPException

from kuro_backend import chat_history
from kuro_backend.export_engine.export_models import ExportPayload

_ALLOWED_TRANSCRIPT_KEYS = {
    "id",
    "timestamp",
    "role",
    "persona",
    "role_label",
    "content",
    "attachments",
    "is_edited",
    "is_bookmarked",
}


def validate_export_permission(username: str, chat_id: str, message_ids: list[int] | None = None) -> dict:
    session = chat_history.get_session(chat_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    if session.get("username") != username:
        raise HTTPException(status_code=403, detail="Forbidden")

    if message_ids is not None:
        if not message_ids:
            raise HTTPException(status_code=400, detail="message_ids is required for selected_messages")
        for message_id in message_ids:
            msg = chat_history.get_message_by_id(message_id)
            if not msg:
                raise HTTPException(status_code=404, detail=f"Message {message_id} not found")
            if msg.get("chat_id") != chat_id or msg.get("username") != username:
                raise HTTPException(status_code=403, detail="Forbidden")
    return session


def validate_compliance_export_permission(username: str) -> None:
    """Compliance export is restricted because compliance DB is not user-scoped."""
    admin_username = os.getenv("ADMIN_USERNAME", "Pantronux")
    if username != admin_username:
        raise HTTPException(status_code=403, detail="Compliance export is restricted to admin")


def sanitize_export_payload(payload: ExportPayload) -> ExportPayload:
    cleaned_transcript = []
    for item in payload.transcript:
        cleaned = {key: item.get(key) for key in _ALLOWED_TRANSCRIPT_KEYS if key in item}
        cleaned["content"] = cleaned.get("content", "") if isinstance(cleaned.get("content", ""), str) else str(cleaned.get("content", ""))
        cleaned["attachments"] = [str(v) for v in (cleaned.get("attachments") or [])]
        cleaned_transcript.append(cleaned)

    metadata = {str(key): str(value) for key, value in payload.metadata.items()}
    return payload.model_copy(update={"metadata": metadata, "transcript": cleaned_transcript})
