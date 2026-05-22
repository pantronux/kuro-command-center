"""FastAPI routes for Telegram API V2."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from kuro_backend.config import settings
from kuro_backend.telegram_v2.commands import TelegramV2CommandRouter
from kuro_backend.telegram_v2.dlq import TelegramV2DLQ
from kuro_backend.telegram_v2.inbound import TelegramV2InboundProcessor
from kuro_backend.telegram_v2.notifier import TelegramV2Notifier
from kuro_backend.telegram_v2.queue import TelegramV2QueueStore
from kuro_backend.telegram_v2.schemas import TelegramHealth, TelegramSenderMappingRequest
from kuro_backend.telegram_v2.security import configured_webhook_secret, token_configured, validate_webhook_secret


def is_telegram_v2_enabled() -> bool:
    return bool(getattr(settings, "KURO_TELEGRAM_V2_ENABLED", False))


def _success(data: Any = None, **extra: Any) -> Dict[str, Any]:
    payload = {"status": "success", "data": data, "error": None}
    payload.update(extra)
    return payload


class TelegramV2Service:
    def __init__(
        self,
        *,
        queue: Optional[TelegramV2QueueStore] = None,
        notifier: Optional[TelegramV2Notifier] = None,
        command_router: Optional[TelegramV2CommandRouter] = None,
        send_webhook_responses: bool = False,
    ) -> None:
        self.queue = queue or TelegramV2QueueStore()
        self.notifier = notifier or TelegramV2Notifier(queue=self.queue)
        self.command_router = command_router or TelegramV2CommandRouter()
        self.inbound = TelegramV2InboundProcessor(
            queue=self.queue,
            notifier=self.notifier,
            command_router=self.command_router,
            send_responses=send_webhook_responses,
        )
        self.dlq = TelegramV2DLQ(queue=self.queue, notifier=self.notifier)

    def health(self) -> TelegramHealth:
        return TelegramHealth(
            enabled=is_telegram_v2_enabled(),
            webhook_secret_configured=bool(configured_webhook_secret()),
            token_configured=token_configured(),
            queue_counts=self.queue.counts(),
            mapping_count=self.queue.active_mapping_count(),
        )

    def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.inbound.handle_webhook(payload).model_dump()


def create_telegram_v2_router(
    *,
    admin_dependency: Callable[..., Dict[str, str]],
    service: Optional[TelegramV2Service] = None,
) -> APIRouter:
    router = APIRouter()
    service_instance = service

    def _service() -> TelegramV2Service:
        nonlocal service_instance
        if service_instance is None:
            service_instance = TelegramV2Service()
        return service_instance

    def _require_enabled() -> None:
        if not is_telegram_v2_enabled():
            raise HTTPException(status_code=404, detail="Telegram API V2 is disabled")

    @router.post("/api/telegram/webhook")
    async def telegram_v2_webhook(request: Request):
        _require_enabled()
        validate_webhook_secret(request.headers)
        payload = await request.json()
        return _success(_service().handle_webhook(payload))

    @router.get("/api/admin/telegram-v2/health")
    async def telegram_v2_health(_admin: Dict[str, str] = Depends(admin_dependency)):
        return _success(_service().health().model_dump())

    @router.get("/api/admin/telegram-v2/dlq")
    async def telegram_v2_dlq(
        limit: int = Query(default=100, ge=1, le=500),
        _admin: Dict[str, str] = Depends(admin_dependency),
    ):
        return _success([message.model_dump() for message in _service().dlq.list_dead(limit=limit)])

    @router.post("/api/admin/telegram-v2/dlq/{message_id}/retry")
    async def telegram_v2_retry_dlq(
        message_id: str,
        _admin: Dict[str, str] = Depends(admin_dependency),
    ):
        try:
            message = _service().dlq.retry(message_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="DLQ message not found") from exc
        return _success(message.model_dump())

    @router.get("/api/admin/telegram-v2/mappings")
    async def telegram_v2_mappings(_admin: Dict[str, str] = Depends(admin_dependency)):
        return _success([mapping.model_dump() for mapping in _service().queue.list_mappings()])

    @router.post("/api/admin/telegram-v2/mappings")
    async def telegram_v2_upsert_mapping(
        payload: TelegramSenderMappingRequest,
        _admin: Dict[str, str] = Depends(admin_dependency),
    ):
        return _success(_service().queue.upsert_mapping(payload).model_dump())

    return router
