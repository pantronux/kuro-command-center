"""API V2 middleware, response envelope, and compatibility tests."""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WORKING_DIR", str(PROJECT_ROOT))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *args, **kwargs):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

if "phoenix" not in sys.modules:
    fake_phoenix = types.ModuleType("phoenix")

    class _FakePhoenixApp:
        url = "http://localhost:6006"

        def close(self):
            return None

    fake_phoenix.launch_app = lambda *args, **kwargs: _FakePhoenixApp()
    sys.modules["phoenix"] = fake_phoenix

from kuro_backend.api_v2 import create_api_v2_router
from kuro_backend.api_v2.middleware import APIRequestControls, install_api_v2_middleware
from kuro_backend.api_v2.rate_limit import RateLimitDecision
from kuro_backend.api_v2.responses import success_envelope
from kuro_backend.config import settings


class StaticLimiter:
    def __init__(self, decision: RateLimitDecision) -> None:
        self.decision = decision
        self.requests = []

    def check(self, request):
        self.requests.append(request)
        return self.decision


def _api_app(
    *,
    admin_allowed: bool = True,
    controls: APIRequestControls | None = None,
    rate_limiter: Any = None,
) -> FastAPI:
    app = FastAPI()
    install_api_v2_middleware(
        app,
        controls=controls or APIRequestControls(),
        rate_limiter=rate_limiter,
    )

    def auth_dep() -> Dict[str, str]:
        return {"username": "Pantronux"}

    def admin_dep() -> Dict[str, str]:
        if not admin_allowed:
            raise HTTPException(status_code=403, detail="Forbidden: Admin access required.")
        return {"username": "Pantronux"}

    app.include_router(
        create_api_v2_router(
            auth_dependency=auth_dep,
            admin_dependency=admin_dep,
            app_for_openapi=app,
        )
    )

    @app.post("/api/v2/echo")
    async def echo(request: Request):
        body = await request.body()
        return success_envelope({"size": len(body)}, request=request)

    @app.get("/api/v2/stream")
    async def stream():
        async def _events():
            yield "data: one\n\n"
            yield "data: two\n\n"

        return StreamingResponse(_events(), media_type="text/event-stream")

    return app


def test_trace_id_header_exists(monkeypatch):
    monkeypatch.setattr(settings, "KURO_API_V2_ENABLED", False, raising=False)
    client = TestClient(_api_app())

    response = client.get("/api/v2/health", headers={"X-Trace-ID": "trace_test_123"})

    assert response.status_code == 200
    assert response.headers["X-Trace-ID"] == "trace_test_123"
    body = response.json()
    assert body["status"] == "success"
    assert body["trace_id"] == "trace_test_123"
    assert body["meta"] == {}


def test_standardized_error_response(monkeypatch):
    monkeypatch.setattr(settings, "KURO_API_V2_ENABLED", True, raising=False)
    client = TestClient(_api_app())

    response = client.get("/api/v2/errors/provider-unavailable")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["data"] is None
    assert body["error"]["code"] == "provider_unavailable"
    assert body["trace_id"].startswith("trace_")


def test_admin_route_forbidden_for_non_admin(monkeypatch):
    monkeypatch.setattr(settings, "KURO_API_V2_ENABLED", True, raising=False)
    client = TestClient(_api_app(admin_allowed=False))

    response = client.get("/api/v2/admin/probe")

    assert response.status_code == 403
    body = response.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "forbidden"
    assert "admin" in body["error"]["message"].lower()


def test_rate_limit_mocked():
    limiter = StaticLimiter(
        RateLimitDecision(
            allowed=False,
            limit=1,
            remaining=0,
            reset_after_seconds=30,
            reason="mocked route-class limit",
        )
    )
    client = TestClient(_api_app(rate_limiter=limiter))

    response = client.get("/api/v2/health", headers={"X-Kuro-Username": "Pantronux"})

    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "rate_limited"
    assert body["meta"]["reset_after_seconds"] == 30
    assert response.headers["Retry-After"] == "30"
    assert limiter.requests[0].identifier == "user:Pantronux"


def test_request_size_limit_mocked():
    client = TestClient(
        _api_app(controls=APIRequestControls(request_size_limit_bytes=4))
    )

    response = client.post("/api/v2/echo", content=b"too-large")

    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["meta"]["request_size_limit_bytes"] == 4


def test_feature_disabled_error_shape(monkeypatch):
    monkeypatch.setattr(settings, "KURO_API_V2_ENABLED", False, raising=False)
    client = TestClient(_api_app())

    response = client.get("/api/v2/feature-disabled")

    assert response.status_code == 404
    body = response.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "feature_disabled"
    assert body["meta"]["flag"] == "KURO_API_V2_ENABLED"


def test_middleware_does_not_break_streaming():
    client = TestClient(_api_app())

    response = client.get("/api/v2/stream")

    assert response.status_code == 200
    assert response.headers["X-Trace-ID"].startswith("trace_")
    assert "data: one" in response.text
    assert "data: two" in response.text


def test_existing_chat_route_still_works(monkeypatch):
    import main

    monkeypatch.setattr(main.settings, "KURO_CHAT_V2_ENABLED", False, raising=False)
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": "tester"})

    async def _fake_stream(*args, **kwargs):
        yield "api-v2-safe"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = TestClient(main.app)
    response = client.post(
        "/api/chat/stream",
        data={"message": "hello", "persona": "consultant"},
        headers={"X-Chat-Session": "session_api_v2_12345"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    assert response.headers["X-Trace-ID"].startswith("trace_")
    events = [
        block
        for block in response.text.replace("\r\n", "\n").split("\n\n")
        if block.strip()
    ]
    assert any("api-v2-safe" in event for event in events)
    assert any("event: complete" in event for event in events)
