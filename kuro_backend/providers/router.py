"""FastAPI routes for Provider Registry V2."""
from __future__ import annotations

from typing import Callable, Dict

from fastapi import APIRouter, Depends

from kuro_backend.providers.errors import ProviderUnavailableError
from kuro_backend.providers.ollama_provider import OllamaProvider
from kuro_backend.providers.registry import get_provider_registry
from kuro_backend.providers.schemas import ProviderRequest


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

    @router.get("/api/admin/providers/ollama/health")
    async def ollama_health(_admin: Dict[str, str] = Depends(admin_dependency)):
        provider = get_provider_registry().provider("ollama")
        if not isinstance(provider, OllamaProvider):
            return _success(
                {
                    "provider": "ollama",
                    "enabled": False,
                    "status": "unavailable",
                    "reason": "provider_not_registered",
                }
            )
        return _success(provider.health_check(include_models=True, public=False))

    @router.get("/api/admin/providers/ollama/models")
    async def ollama_models(_admin: Dict[str, str] = Depends(admin_dependency)):
        provider = get_provider_registry().provider("ollama")
        if not isinstance(provider, OllamaProvider):
            return _success({"provider": "ollama", "enabled": False, "models": []})
        try:
            return _success(await provider.list_models())
        except ProviderUnavailableError as exc:
            return _success(
                {
                    "provider": "ollama",
                    "enabled": provider.enabled(),
                    "models": [],
                    "error": {"code": str(exc)},
                }
            )

    @router.post("/api/admin/providers/ollama/smoke-test")
    async def ollama_smoke_test(_admin: Dict[str, str] = Depends(admin_dependency)):
        provider = get_provider_registry().provider("ollama")
        if not isinstance(provider, OllamaProvider) or not provider.enabled():
            return _success(
                {
                    "success": False,
                    "provider": "ollama",
                    "status": "unavailable",
                    "error": {"code": "provider_unavailable"},
                }
            )
        request = ProviderRequest.from_prompt(
            "Reply with exactly: ok",
            model_alias="ollama_local",
            model_id=provider.default_model(),
            temperature=0.0,
            max_output_tokens=8,
        )
        try:
            response = await provider.generate(request, model_id=provider.default_model())
        except ProviderUnavailableError as exc:
            return _success(
                {
                    "success": False,
                    "provider": "ollama",
                    "status": "unavailable",
                    "error": {"code": str(exc)},
                }
            )
        ok = response.content.strip().lower() == "ok"
        return _success(
            {
                "success": ok,
                "provider": "ollama",
                "status": "ok" if ok else "unexpected_response",
            }
        )

    @router.get("/api/models")
    async def public_models():
        return _success(get_provider_registry().public_models())

    return router
