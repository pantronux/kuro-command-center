"""Chat V2 service and additive FastAPI router."""
from __future__ import annotations

import inspect
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from kuro_backend import chat_history
from kuro_backend.config import settings
from kuro_backend.chat_v2.history import ChatV2HistoryService
from kuro_backend.chat_v2.schemas import (
    ChatMessageEditRequest,
    ChatSessionPatch,
    ChatSessionSettings,
)
from kuro_backend.chat_v2.session_settings import ChatSettingsRepository
from kuro_backend.chat_v2.streaming import chat_v2_replay_buffer, stream_chat_v2_envelopes
from kuro_backend.chat_v2.telemetry import record_chat_v2_event


TokenStreamFactory = Callable[..., AsyncIterator[str]]


def is_chat_v2_enabled() -> bool:
    return bool(getattr(settings, "KURO_CHAT_V2_ENABLED", False))


def _success(data: Any = None, **extra: Any) -> Dict[str, Any]:
    payload = {"status": "success", "data": data, "error": None}
    payload.update(extra)
    return payload


async def _iterate_token_source(factory_result: Any) -> AsyncIterator[str]:
    if inspect.isawaitable(factory_result):
        factory_result = await factory_result
    if hasattr(factory_result, "__aiter__"):
        async for chunk in factory_result:
            yield str(chunk or "")
        return
    for chunk in factory_result or []:
        yield str(chunk or "")


class ChatV2Service:
    def __init__(
        self,
        *,
        history: Optional[ChatV2HistoryService] = None,
        settings_repo: Optional[ChatSettingsRepository] = None,
    ) -> None:
        self.history = history or ChatV2HistoryService()
        self.settings = settings_repo or ChatSettingsRepository()

    def get_settings(self, *, chat_id: str, username: str) -> ChatSessionSettings:
        settings_value = self.settings.get(chat_id=chat_id, username=username)
        if settings_value is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        return settings_value

    def save_settings(
        self,
        *,
        chat_id: str,
        username: str,
        payload: ChatSessionSettings,
    ) -> ChatSessionSettings:
        self.history.get_session(chat_id=chat_id, username=username)
        return self.settings.save(chat_id=chat_id, username=username, settings=payload)


def create_chat_v2_router(
    *,
    auth_dependency: Callable[..., Dict[str, str]],
    token_stream_factory: Optional[TokenStreamFactory] = None,
) -> APIRouter:
    router = APIRouter()
    service = ChatV2Service()

    def _require_enabled() -> None:
        if not is_chat_v2_enabled():
            raise HTTPException(status_code=404, detail="Chat V2 is disabled")

    @router.get("/api/chats/{chat_id}")
    async def get_chat_v2(
        chat_id: str,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_enabled()
        return _success(service.history.get_session(chat_id=chat_id, username=user["username"]))

    @router.patch("/api/chats/{chat_id}")
    async def patch_chat_v2(
        chat_id: str,
        patch: ChatSessionPatch,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_enabled()
        return _success(
            service.history.patch_session(
                chat_id=chat_id,
                username=user["username"],
                patch=patch,
            )
        )

    @router.post("/api/chats/{chat_id}/settings")
    async def save_chat_v2_settings(
        chat_id: str,
        payload: ChatSessionSettings,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_enabled()
        stored = service.save_settings(chat_id=chat_id, username=user["username"], payload=payload)
        return _success(stored.model_dump())

    @router.post("/api/chats/{chat_id}/messages/{message_id}/edit")
    async def edit_chat_v2_message(
        chat_id: str,
        message_id: int,
        payload: ChatMessageEditRequest,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_enabled()
        result = service.history.edit_message(
            chat_id=chat_id,
            message_id=message_id,
            username=user["username"],
            new_content=payload.new_content,
        )
        return _success(result.model_dump())

    @router.post("/api/chat/v2/stream")
    async def chat_v2_stream(
        request: Request,
        message: str = Form(""),
        persona: str = Form("consultant"),
        chat_id: str = Form(""),
        user: Dict[str, str] = Depends(auth_dependency),
        last_event_id_query: Optional[int] = Query(default=None, alias="last_event_id"),
    ):
        _require_enabled()
        username = user["username"]
        final_chat_id = chat_id or request.headers.get("X-Chat-Session") or f"chat_{uuid.uuid4().hex[:12]}"
        trace_id = str(getattr(request.state, "trace_id", "") or f"chatv2_{uuid.uuid4().hex}")
        session = chat_history.get_session(final_chat_id, username=username)
        if not session:
            chat_history.create_session(final_chat_id, username, persona, "New Chat")

        last_event_id_header = request.headers.get("Last-Event-ID")
        try:
            last_event_id = (
                int(last_event_id_header)
                if last_event_id_header is not None
                else last_event_id_query
            )
        except (TypeError, ValueError):
            last_event_id = last_event_id_query

        full_response_saved = False
        user_message_saved = False
        user_message_id: Optional[int] = None

        async def token_source() -> AsyncIterator[str]:
            nonlocal user_message_saved, user_message_id
            if not user_message_saved:
                user_message_id = chat_history.add_message(
                    "web",
                    "user",
                    message,
                    [],
                    persona=persona,
                    request_id=trace_id,
                    username=username,
                    chat_id=final_chat_id,
                    trace_id=trace_id,
                    event_seq=chat_history.get_next_event_seq(final_chat_id),
                    branch_id=f"branch_{final_chat_id}",
                )
                user_message_saved = True
            if token_stream_factory is None:
                yield message
                return
            async for token in _iterate_token_source(
                token_stream_factory(
                    message=message,
                    persona=persona,
                    username=username,
                    chat_id=final_chat_id,
                    trace_id=trace_id,
                    request=request,
                )
            ):
                yield token

        async def on_complete(response_text: str) -> None:
            nonlocal full_response_saved
            if full_response_saved:
                return
            chat_history.add_message(
                "web",
                "assistant",
                response_text,
                [],
                persona=persona,
                request_id=trace_id,
                username=username,
                chat_id=final_chat_id,
                trace_id=trace_id,
                event_seq=chat_history.get_next_event_seq(final_chat_id),
                parent_message_id=user_message_id,
                branch_id=f"branch_{final_chat_id}",
            )
            full_response_saved = True

        async def generator() -> AsyncIterator[str]:
            async for frame in stream_chat_v2_envelopes(
                chat_id=final_chat_id,
                trace_id=trace_id,
                token_source=token_source,
                last_event_id=last_event_id,
                request=request,
                replay_buffer=chat_v2_replay_buffer,
                on_complete=on_complete,
            ):
                yield frame

        record_chat_v2_event("stream_started", chat_id=final_chat_id, trace_id=trace_id, username=username)
        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
