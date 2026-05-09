from __future__ import annotations

import json
from datetime import datetime

from fastapi import HTTPException

from kuro_backend import chat_history
from kuro_backend.export_engine.export_models import ExportPayload


def _normalize_content(content) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, indent=2)


def _role_label(message: dict, persona: str) -> str:
    if message.get("role") == "user":
        return "User"
    return f"Kuro ({persona})"


def _build_transcript(messages: list[dict], persona: str) -> list[dict]:
    transcript = []
    for msg in messages:
        transcript.append(
            {
                "id": msg.get("id"),
                "timestamp": msg.get("timestamp"),
                "role": msg.get("role"),
                "persona": msg.get("persona"),
                "role_label": _role_label(msg, persona),
                "content": _normalize_content(msg.get("content", "")),
                "attachments": msg.get("attachments") or [],
                "is_edited": msg.get("is_edited", 0),
                "is_bookmarked": msg.get("is_bookmarked", 0),
            }
        )
    return transcript


def render_chat_session(chat_id: str, username: str) -> ExportPayload:
    session = chat_history.get_session(chat_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    messages = chat_history.get_history(chat_id=chat_id, username=username, limit=9999)
    persona = session.get("persona", "consultant")
    exported_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    transcript = _build_transcript(messages, persona)
    return ExportPayload(
        title=session.get("title") or "New Chat",
        export_type="chat_session",
        username=username,
        source_chat_id=chat_id,
        metadata={
            "exported_at": exported_at,
            "persona": persona,
            "message_count": len(transcript),
            "chat_id": chat_id,
        },
        transcript=transcript,
    )


def render_selected_messages(chat_id: str, message_ids: list[int], username: str) -> ExportPayload:
    if not message_ids:
        raise HTTPException(status_code=400, detail="message_ids is required for selected_messages")

    session = chat_history.get_session(chat_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    all_messages = chat_history.get_history(chat_id=chat_id, username=username, limit=9999)
    selected = [msg for msg in all_messages if msg.get("id") in set(message_ids)]
    selected.sort(key=lambda item: int(item.get("id") or 0))
    persona = session.get("persona", "consultant")
    exported_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    transcript = _build_transcript(selected, persona)
    return ExportPayload(
        title=f"{session.get('title') or 'New Chat'} - Selected Messages",
        export_type="selected_messages",
        username=username,
        source_chat_id=chat_id,
        metadata={
            "exported_at": exported_at,
            "persona": persona,
            "message_count": len(transcript),
            "chat_id": chat_id,
            "selected_message_ids": ",".join(str(mid) for mid in message_ids),
        },
        transcript=transcript,
    )
