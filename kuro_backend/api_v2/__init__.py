"""API V2 additive control-plane package."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from kuro_backend.api_v2.authz import principal_from_user
from kuro_backend.api_v2.errors import APIError
from kuro_backend.api_v2.middleware import APIRequestControls
from kuro_backend.api_v2.openapi import public_openapi_schema
from kuro_backend.api_v2.rate_limit import env_rate_limit_enabled
from kuro_backend.api_v2.responses import json_error, success_envelope
from kuro_backend.api_v2.schemas import APIHealth, APIErrorCode, Principal
from kuro_backend.config import settings


ERROR_CODES: list[APIErrorCode] = [
    "unauthorized",
    "forbidden",
    "not_found",
    "validation_error",
    "feature_disabled",
    "rate_limited",
    "provider_unavailable",
    "tool_denied",
    "memory_denied",
    "internal_error",
]


def is_api_v2_enabled() -> bool:
    return bool(getattr(settings, "KURO_API_V2_ENABLED", False))


def create_api_v2_router(
    *,
    auth_dependency: Optional[Callable[..., Dict[str, Any]]] = None,
    admin_dependency: Optional[Callable[..., Dict[str, Any]]] = None,
    app_for_openapi: Any = None,
) -> APIRouter:
    router = APIRouter()

    def _missing_auth() -> Dict[str, Any]:
        raise HTTPException(status_code=401, detail="Authentication required")

    def _missing_admin() -> Dict[str, Any]:
        raise HTTPException(status_code=403, detail="Admin dependency is not configured")

    auth_dep = auth_dependency or _missing_auth
    admin_dep = admin_dependency or _missing_admin

    @router.get("/api/v2/health", tags=["api-v2"])
    async def api_v2_health(request: Request):
        controls = APIRequestControls.from_env()
        health = APIHealth(
            enabled=is_api_v2_enabled(),
            error_codes=ERROR_CODES,
            rate_limit_enabled=env_rate_limit_enabled(),
            request_size_limit_bytes=controls.request_size_limit_bytes,
        )
        return success_envelope(health.model_dump(), request=request)

    @router.get("/api/v2/feature-disabled", tags=["api-v2"])
    async def api_v2_feature_disabled(request: Request):
        if not is_api_v2_enabled():
            return json_error(
                code="feature_disabled",
                message="API V2 is disabled",
                request=request,
                status_code=404,
                meta={"flag": "KURO_API_V2_ENABLED"},
            )
        return success_envelope({"enabled": True}, request=request)

    @router.get("/api/v2/errors/provider-unavailable", tags=["api-v2"])
    async def api_v2_provider_unavailable():
        raise APIError(
            code="provider_unavailable",
            message="Provider unavailable",
            status_code=503,
        )

    @router.get("/api/v2/me", tags=["api-v2"])
    async def api_v2_me(
        request: Request,
        user: Dict[str, Any] = Depends(auth_dep),
    ):
        principal = principal_from_user(user)
        return success_envelope(principal.model_dump(), request=request)

    @router.get("/api/v2/admin/probe", tags=["api-v2-admin"])
    async def api_v2_admin_probe(
        request: Request,
        user: Dict[str, Any] = Depends(admin_dep),
    ):
        principal = principal_from_user(user)
        return success_envelope({"admin": True, "principal": principal.model_dump()}, request=request)

    @router.get("/api/v2/openapi/public", tags=["api-v2"])
    async def api_v2_public_openapi(request: Request):
        if app_for_openapi is None:
            return success_envelope({"paths": []}, request=request)
        schema = public_openapi_schema(app_for_openapi)
        return success_envelope(schema, request=request)

    return router


__all__ = [
    "APIHealth",
    "Principal",
    "create_api_v2_router",
    "is_api_v2_enabled",
]
