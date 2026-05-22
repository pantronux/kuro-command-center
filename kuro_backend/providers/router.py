"""FastAPI routes for Provider Registry V2."""
from __future__ import annotations

from typing import Callable, Dict

from fastapi import APIRouter, Depends

from kuro_backend.providers.registry import get_provider_registry


def _success(data):
    return {"status": "success", "data": data, "error": None}


def create_provider_registry_router(*, admin_dependency: Callable[..., Dict[str, str]]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/admin/providers")
    async def list_admin_providers(_admin: Dict[str, str] = Depends(admin_dependency)):
        registry = get_provider_registry()
        health = registry.health_check()
        return _success(
            {
                "enabled": health.enabled,
                "providers": {
                    key: value.model_dump()
                    for key, value in health.providers.items()
                },
                "aliases": {
                    key: value.model_dump()
                    for key, value in health.aliases.items()
                },
            }
        )

    @router.get("/api/admin/providers/health")
    async def provider_health(_admin: Dict[str, str] = Depends(admin_dependency)):
        registry = get_provider_registry()
        health = registry.health_check()
        return _success(health.model_dump())

    @router.get("/api/models")
    async def public_models():
        return _success(get_provider_registry().public_models())

    return router
