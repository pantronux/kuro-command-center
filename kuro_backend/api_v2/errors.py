"""API V2 error taxonomy and normalization helpers."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kuro_backend.api_v2.responses import json_error
from kuro_backend.api_v2.schemas import APIErrorCode


ERROR_STATUS: Dict[APIErrorCode, int] = {
    "unauthorized": 401,
    "forbidden": 403,
    "not_found": 404,
    "validation_error": 400,
    "feature_disabled": 404,
    "rate_limited": 429,
    "provider_unavailable": 503,
    "tool_denied": 403,
    "memory_denied": 403,
    "internal_error": 500,
}


def code_for_status(status_code: int) -> APIErrorCode:
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code == 429:
        return "rate_limited"
    if status_code in {400, 413, 422}:
        return "validation_error"
    if status_code == 503:
        return "provider_unavailable"
    return "internal_error"


class APIError(Exception):
    def __init__(
        self,
        *,
        code: APIErrorCode,
        message: str,
        status_code: Optional[int] = None,
        detail: Any = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = int(status_code or ERROR_STATUS.get(code, 500))
        self.detail = detail
        self.meta = meta or {}
        super().__init__(message)


def is_api_v2_path(request: Request) -> bool:
    return request.url.path.startswith("/api/v2")


async def api_v2_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return json_error(
        code=exc.code,
        message=exc.message,
        request=request,
        detail=exc.detail,
        meta=exc.meta,
        status_code=exc.status_code,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if not is_api_v2_path(request):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
    code = code_for_status(exc.status_code)
    message = str(exc.detail or code.replace("_", " ").title())
    return json_error(
        code=code,
        message=message,
        request=request,
        detail=exc.detail,
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    if not is_api_v2_path(request):
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
    return json_error(
        code="validation_error",
        message="Validation error",
        request=request,
        detail=exc.errors(),
        status_code=422,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not is_api_v2_path(request):
        raise exc
    return json_error(
        code="internal_error",
        message="Internal error",
        request=request,
        detail=None,
        meta={"exception_type": exc.__class__.__name__},
        status_code=500,
    )


def install_api_v2_exception_handlers(app: FastAPI) -> None:
    if getattr(app.state, "api_v2_exception_handlers_installed", False):
        return
    app.add_exception_handler(APIError, api_v2_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.state.api_v2_exception_handlers_installed = True
