"""Standard response helpers for additive API V2 surfaces."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from kuro_backend.api_v2.schemas import APIErrorCode


def trace_id_from_request(request: Optional[Request] = None, explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    if request is not None:
        state_trace = getattr(request.state, "trace_id", None)
        if state_trace:
            return str(state_trace)
        header_trace = request.headers.get("X-Trace-ID")
        if header_trace:
            return str(header_trace)
    return "trace_unavailable"


def success_envelope(
    data: Any = None,
    *,
    request: Optional[Request] = None,
    trace_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "status": "success",
        "data": data,
        "error": None,
        "trace_id": trace_id_from_request(request, trace_id),
        "meta": meta or {},
    }


def error_envelope(
    *,
    code: APIErrorCode,
    message: str,
    request: Optional[Request] = None,
    trace_id: Optional[str] = None,
    detail: Any = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    error: Dict[str, Any] = {
        "code": code,
        "message": message,
        "detail": detail,
    }
    return {
        "status": "error",
        "data": None,
        "error": error,
        "trace_id": trace_id_from_request(request, trace_id),
        "meta": meta or {},
    }


def json_success(
    data: Any = None,
    *,
    request: Optional[Request] = None,
    status_code: int = 200,
    meta: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=success_envelope(data=data, request=request, meta=meta),
    )


def json_error(
    *,
    code: APIErrorCode,
    message: str,
    request: Optional[Request] = None,
    trace_id: Optional[str] = None,
    detail: Any = None,
    meta: Optional[Dict[str, Any]] = None,
    status_code: int = 500,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_envelope(
            code=code,
            message=message,
            request=request,
            trace_id=trace_id,
            detail=detail,
            meta=meta,
        ),
        headers=headers,
    )
