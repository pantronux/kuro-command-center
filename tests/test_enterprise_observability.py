"""Enterprise observability and AI security governance tests."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WORKING_DIR", str(PROJECT_ROOT))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kuro_backend.enterprise_observability.audit import EnterpriseObservabilityStore
from kuro_backend.enterprise_observability.dashboards import (
    EnterpriseObservabilityService,
    create_enterprise_observability_router,
)


@pytest.fixture
def observability_service(tmp_path):
    store = EnterpriseObservabilityStore(tmp_path / "enterprise_observability.db")
    return EnterpriseObservabilityService(store)


def _app(service: EnterpriseObservabilityService, *, admin_allowed: bool = True) -> FastAPI:
    app = FastAPI()

    def admin_dep() -> Dict[str, str]:
        if not admin_allowed:
            raise HTTPException(status_code=403, detail="Forbidden: Admin access required.")
        return {"username": "Pantronux", "role": "Administrator"}

    app.include_router(
        create_enterprise_observability_router(
            admin_dependency=admin_dep,
            service=service,
        )
    )
    return app


def test_observability_routes_require_admin(observability_service):
    client = TestClient(_app(observability_service, admin_allowed=False))
    routes = [
        "/api/admin/observability/summary",
        "/api/admin/observability/traces",
        "/api/admin/observability/security-events",
        "/api/admin/observability/evals",
        "/api/admin/observability/market",
        "/api/admin/observability/memory",
    ]

    for route in routes:
        response = client.get(route)
        assert response.status_code == 403, route


def test_traces_do_not_contain_secrets(monkeypatch, observability_service):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini-key-for-test")
    observability_service.trace_exporter.record_trace(
        name="provider.generate",
        span_category="llm",
        actor_username="Pantronux",
        trace_id="trace_secret_test",
        attributes={
            "provider": "gemini",
            "model_alias": "gemini_fast",
            "api_key": "secret-gemini-key-for-test",
            "Authorization": "Bearer abcdefghijklmnop",
            "prompt": "please summarize private prompt",
            "safe": "visible",
        },
    )
    client = TestClient(_app(observability_service))

    response = client.get("/api/admin/observability/traces")

    assert response.status_code == 200
    serialized = json.dumps(response.json(), sort_keys=True)
    assert "secret-gemini-key-for-test" not in serialized
    assert "Bearer abcdefghijklmnop" not in serialized
    assert "please summarize private prompt" not in serialized
    assert "visible" in serialized
    assert "[redacted" in serialized


def test_security_event_persisted(observability_service):
    observability_service.security.record_event(
        event_type="prompt_injection_detected",
        actor_username="Pantronux",
        workspace_id="default",
        runtime_id="sovereign",
        trace_id="trace_sec_1",
        metadata={"detector": "smoke"},
    )
    client = TestClient(_app(observability_service))

    response = client.get("/api/admin/observability/security-events")

    assert response.status_code == 200
    events = response.json()["data"]
    assert events[0]["event_type"] == "prompt_injection_detected"
    assert events[0]["trace_id"] == "trace_sec_1"


def test_memory_conflict_metric_increments(observability_service):
    observability_service.metrics.record_memory_conflict(username="Pantronux")
    observability_service.metrics.record_memory_conflict(username="Pantronux")
    client = TestClient(_app(observability_service))

    response = client.get("/api/admin/observability/memory")

    assert response.status_code == 200
    metrics = response.json()["data"]["metrics"]
    assert metrics["memory.conflicts"]["total"] == 2.0
    assert metrics["memory.conflicts"]["count"] == 2


def test_tool_denial_event_logged(observability_service):
    observability_service.security.record_tool_denied(
        tool_id="openclaw_bridge",
        actor_username="Faikhira",
        reason="requires_admin",
        runtime_id="sovereign",
        workspace_id="default",
        trace_id="trace_tool_denied",
    )
    client = TestClient(_app(observability_service))

    security = client.get("/api/admin/observability/security-events").json()["data"]
    summary = client.get("/api/admin/observability/summary").json()["data"]

    assert any(event["event_type"] == "tool_denied" for event in security)
    assert summary["metrics"]["tool.denials"]["total"] == 1.0


def test_provider_fallback_event_logged(observability_service):
    observability_service.security.record_provider_error(
        provider="openai",
        model_alias="openai_nano",
        fallback_alias="gemini_fast",
        error="provider unavailable",
        trace_id="trace_provider_fallback",
    )
    client = TestClient(_app(observability_service))

    events = client.get("/api/admin/observability/security-events").json()["data"]
    summary = client.get("/api/admin/observability/summary").json()["data"]

    assert any(event["event_type"] == "provider_error" for event in events)
    assert summary["metrics"]["provider.errors"]["total"] == 1.0
    assert summary["metrics"]["provider.fallbacks"]["total"] == 1.0


def test_sse_disconnect_counted(observability_service):
    observability_service.metrics.record_sse_disconnect(chat_id="chat_1", trace_id="trace_sse")
    client = TestClient(_app(observability_service))

    response = client.get("/api/admin/observability/summary")

    assert response.status_code == 200
    assert response.json()["data"]["metrics"]["sse.disconnects"]["total"] == 1.0


def test_smoke_evals_can_be_run_from_admin_route(observability_service):
    client = TestClient(_app(observability_service))

    response = client.get("/api/admin/observability/evals?run_smoke=true")

    assert response.status_code == 200
    eval_names = {item["eval_name"] for item in response.json()["data"]}
    assert "memory_retrieval_quality_smoke" in eval_names
    assert "sse_contract" in eval_names
    assert "market_sentinel_source_quality" in eval_names
    assert "provider_fallback" in eval_names
    assert "boundary_leakage" in eval_names
