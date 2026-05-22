"""Chat V2 history, pagination, lineage, and ownership service."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from kuro_backend import chat_history
from kuro_backend.chat_v2.attachments import sanitize_message_payload
from kuro_backend.chat_v2.schemas import (
    ChatMessageEditResult,
    ChatMessagePage,
    ChatMessageRegenerateResult,
    ChatSessionCreate,
    ChatSessionPatch,
)
from kuro_backend.chat_v2.telemetry import record_chat_v2_event


class ChatV2HistoryService:
    def ensure_migrations(self) -> None:
        chat_history.init_db()

    def list_sessions(
        self,
        *,
        username: str,
        persona: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        self.ensure_migrations()
        return chat_history.get_sessions(username, persona, limit=limit, offset=offset)

    def create_session(
        self,
        *,
        username: str,
        payload: ChatSessionCreate,
        chat_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.ensure_migrations()
        final_chat_id = chat_id or f"chat_{uuid.uuid4().hex[:12]}"
        settings = payload.settings
        ok = chat_history.create_session(
            chat_id=final_chat_id,
            username=username,
            persona=payload.persona,
            title=payload.title,
            runtime_id=settings.runtime_id,
            workspace_id=payload.workspace_id,
            provider_alias=settings.provider_alias,
            model_alias=settings.model_alias,
            temperature=settings.temperature,
            mode=settings.mode,
            tools_enabled=settings.tools_enabled,
            web_search_enabled=settings.web_search_enabled,
            memory_v3_enabled=settings.memory_v3_enabled,
        )
        if not ok:
            raise HTTPException(status_code=409, detail="Unable to create chat session")
        session = chat_history.get_session(final_chat_id, username=username)
        return dict(session or {"chat_id": final_chat_id, "title": payload.title})

    def get_session(self, *, chat_id: str, username: str) -> Dict[str, Any]:
        self.ensure_migrations()
        session = chat_history.get_session(chat_id, username=username)
        if not session:
            raise HTTPException(status_code=404, detail="Chat not found")
        return dict(session)

    def patch_session(
        self,
        *,
        chat_id: str,
        username: str,
        patch: ChatSessionPatch,
    ) -> Dict[str, Any]:
        self.get_session(chat_id=chat_id, username=username)
        fields: Dict[str, Any] = {}
        if patch.title is not None:
            fields["title"] = patch.title
        if patch.persona is not None:
            fields["persona"] = patch.persona
        if patch.archived is not None:
            fields["archived_at"] = datetime.utcnow().isoformat() if patch.archived else None
        if patch.settings is not None:
            fields.update(patch.settings.model_dump())
        if fields and not chat_history.update_session_fields(chat_id, username, **fields):
            raise HTTPException(status_code=404, detail="Chat not found")
        return self.get_session(chat_id=chat_id, username=username)

    def soft_delete_session(self, *, chat_id: str, username: str) -> Dict[str, Any]:
        self.get_session(chat_id=chat_id, username=username)
        if not chat_history.soft_delete_session(chat_id, username):
            raise HTTPException(status_code=404, detail="Chat not found")
        return {"chat_id": chat_id, "deleted": True}

    def get_messages(
        self,
        *,
        chat_id: str,
        username: str,
        limit: int = 50,
        before_id: Optional[int] = None,
    ) -> ChatMessagePage:
        self.get_session(chat_id=chat_id, username=username)
        page = chat_history.get_history_page(
            chat_id=chat_id,
            username=username,
            limit=limit,
            before_id=before_id,
        )
        page["messages"] = [sanitize_message_payload(row) for row in page.get("messages", [])]
        return ChatMessagePage(**page)

    def edit_message(
        self,
        *,
        chat_id: str,
        message_id: int,
        username: str,
        new_content: str,
    ) -> ChatMessageEditResult:
        self.get_session(chat_id=chat_id, username=username)
        msg = chat_history.get_message_by_id(message_id)
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        if msg.get("username") != username:
            raise HTTPException(status_code=403, detail="You do not own this message")
        if msg.get("chat_id") != chat_id:
            raise HTTPException(status_code=400, detail="Message does not belong to this chat")
        if msg.get("role") != "user":
            raise HTTPException(status_code=400, detail="Only user messages can be edited")
        edit_group_id = msg.get("edit_group_id") or uuid.uuid4().hex
        branch_id = msg.get("branch_id") or f"branch_{uuid.uuid4().hex[:12]}"
        chat_history.save_message_edit(
            original_msg_id=message_id,
            chat_id=chat_id,
            username=username,
            role="user",
            content=str(msg.get("content") or ""),
            edit_type="edit",
            edit_group_id=edit_group_id,
        )
        chat_history.update_message_content(
            message_id,
            new_content,
            edit_group_id=edit_group_id,
            parent_message_id=message_id,
            branch_id=branch_id,
        )
        deleted_count = chat_history.delete_messages_after(message_id, chat_id)
        record_chat_v2_event("message_edited", chat_id=chat_id, message_id=message_id, username=username)
        return ChatMessageEditResult(
            chat_id=chat_id,
            message_id=message_id,
            edit_group_id=edit_group_id,
            branch_id=branch_id,
            deleted_after_count=deleted_count,
        )

    def regenerate_message(
        self,
        *,
        chat_id: str,
        message_id: int,
        username: str,
    ) -> ChatMessageRegenerateResult:
        self.get_session(chat_id=chat_id, username=username)
        msg = chat_history.get_message_by_id(message_id)
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        if msg.get("username") != username:
            raise HTTPException(status_code=403, detail="You do not own this message")
        if msg.get("chat_id") != chat_id:
            raise HTTPException(status_code=400, detail="Message does not belong to this chat")
        if msg.get("role") != "assistant":
            raise HTTPException(status_code=400, detail="Only assistant messages can be regenerated")
        preceding = chat_history.get_preceding_user_message(message_id, chat_id)
        if not preceding:
            raise HTTPException(status_code=400, detail="Cannot find preceding user message to regenerate from")
        edit_group_id = msg.get("edit_group_id") or uuid.uuid4().hex
        chat_history.save_message_edit(
            original_msg_id=message_id,
            chat_id=chat_id,
            username=username,
            role="assistant",
            content=str(msg.get("content") or ""),
            edit_type="regeneration",
            edit_group_id=edit_group_id,
        )
        chat_history.delete_messages_after(message_id - 1, chat_id)
        record_chat_v2_event("message_regenerated", chat_id=chat_id, message_id=message_id, username=username)
        return ChatMessageRegenerateResult(
            chat_id=chat_id,
            message_id=message_id,
            deleted_msg_id=message_id,
            parent_message_id=int(preceding["id"]),
            edit_group_id=edit_group_id,
            preceding_user_message=sanitize_message_payload(dict(preceding)),
        )
