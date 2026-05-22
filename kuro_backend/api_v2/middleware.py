"""ASGI middleware for API V2 tracing, timing, limits, and headers."""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, Iterable, Mapping, MutableMapping, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from kuro_backend.api_v2.errors import install_api_v2_exception_handlers
from kuro_backend.api_v2.rate_limit import RateLimiter, build_rate_limit_request, default_rate_limiter
from kuro_backend.api_v2.responses import error_envelope


DEFAULT_SECURITY_HEADERS: Dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


@dataclass(frozen=True)
class APIRequestControls:
    request_size_limit_bytes: int = 0
    security_headers: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SECURITY_HEADERS))
    apply_exception_normalization_to_prefixes: tuple[str, ...] = ("/api/v2",)

    @classmethod
    def from_env(cls) -> "APIRequestControls":
        limit = int(os.getenv("KURO_API_V2_REQUEST_SIZE_LIMIT_BYTES", "0") or "0")
        return cls(request_size_limit_bytes=max(0, limit))


def cors_sanity_report(
    *,
    allowed_origins: Iterable[str],
    allow_credentials: bool,
) -> Dict[str, object]:
    origins = [origin.strip() for origin in allowed_origins if str(origin).strip()]
    return {
        "allowed_origins_count": len(origins),
        "wildcard_with_credentials": "*" in origins and allow_credentials,
        "has_localhost": any("localhost" in origin or "127.0.0.1" in origin for origin in origins),
    }


class KuroAPIMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        controls: Optional[APIRequestControls] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        self.app = app
        self.controls = controls or APIRequestControls.from_env()
        self.rate_limiter = rate_limiter or default_rate_limiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        path = str(scope.get("path") or "")
        trace_id = headers.get("x-trace-id") or f"trace_{uuid.uuid4().hex[:16]}"
        state = scope.setdefault("state", {})
        if isinstance(state, MutableMapping):
            state["trace_id"] = trace_id
            state["api_v2_started_at"] = time.monotonic()

        size_limit = int(self.controls.request_size_limit_bytes or 0)
        content_length = headers.get("content-length")
        if size_limit > 0 and content_length and int(content_length) > size_limit:
            await self._send_error(
                scope,
                receive,
                send,
                trace_id=trace_id,
                status_code=413,
                code="validation_error",
                message="Request body exceeds configured size limit",
                meta={"request_size_limit_bytes": size_limit},
            )
            return

        client = scope.get("client") or ("unknown", 0)
        decision = self.rate_limiter.check(
            build_rate_limit_request(
                headers={key.lower(): value for key, value in headers.items()},
                client_host=str(client[0] or "unknown"),
                path=path,
                method=str(scope.get("method") or "GET"),
            )
        )
        if not decision.allowed:
            await self._send_error(
                scope,
                receive,
                send,
                trace_id=trace_id,
                status_code=429,
                code="rate_limited",
                message=decision.reason or "Rate limit exceeded",
                meta={
                    "limit": decision.limit,
                    "remaining": decision.remaining,
                    "reset_after_seconds": decision.reset_after_seconds,
                },
                headers={"Retry-After": str(max(1, decision.reset_after_seconds))},
            )
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                response_headers = MutableHeaders(scope=message)
                current_trace_id = str(scope.get("state", {}).get("trace_id") or trace_id)
                response_headers["X-Trace-ID"] = current_trace_id
                started_at = float(scope.get("state", {}).get("api_v2_started_at", time.monotonic()))
                response_headers["X-Response-Time-ms"] = f"{(time.monotonic() - started_at) * 1000:.2f}"
                for header, value in self.controls.security_headers.items():
                    if header not in response_headers:
                        response_headers[header] = value
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            if response_started or not self._should_normalize(path):
                raise
            await self._send_error(
                scope,
                receive,
                send,
                trace_id=str(scope.get("state", {}).get("trace_id") or trace_id),
                status_code=500,
                code="internal_error",
                message="Internal error",
                meta={"exception_type": exc.__class__.__name__},
            )

    def _should_normalize(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self.controls.apply_exception_normalization_to_prefixes)

    async def _send_error(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        trace_id: str,
        status_code: int,
        code: str,
        message: str,
        meta: Optional[Dict[str, object]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        response = JSONResponse(
            status_code=status_code,
            content=error_envelope(
                code=code,  # type: ignore[arg-type]
                message=message,
                trace_id=trace_id,
                meta=meta or {},
            ),
            headers=dict(headers or {}),
        )
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Response-Time-ms"] = "0.00"
        for header, value in self.controls.security_headers.items():
            response.headers.setdefault(header, value)
        await response(scope, receive, send)


def install_api_v2_middleware(
    app: FastAPI,
    *,
    controls: Optional[APIRequestControls] = None,
    rate_limiter: Optional[RateLimiter] = None,
) -> bool:
    install_api_v2_exception_handlers(app)
    if getattr(app.state, "api_v2_middleware_installed", False):
        return False
    app.add_middleware(
        KuroAPIMiddleware,
        controls=controls or APIRequestControls.from_env(),
        rate_limiter=rate_limiter or default_rate_limiter(),
    )
    app.state.api_v2_middleware_installed = True
    return True
