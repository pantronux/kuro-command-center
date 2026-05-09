from __future__ import annotations

import importlib
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from playground_runtime.api.router import create_playground_router
from playground_runtime.providers.adapters.base_adapter import ProviderResponse
from playground_runtime.service import PlaygroundRuntimeService


def _reload_config_module():
    import playground_runtime.config as config_module

    importlib.reload(config_module)
    config_module.get_settings.cache_clear()
    return config_module


def _admin_dependency(x_admin: str | None = Header(default=None)):
    if x_admin != "1":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required.")
    return {"username": "Pantronux"}


def _response(provider_id: str, text: str) -> ProviderResponse:
    return ProviderResponse(
        provider_id=provider_id,
        model_id=f"{provider_id}-model",
        model_version=f"{provider_id}-model-v1",
        request_id=f"req-{provider_id}",
        raw_json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": {"total_tokens": 10}},
        response_text=text,
        finish_reason="stop",
        input_tokens=5,
        output_tokens=5,
        total_tokens=10,
        latency_ms=12.0,
        collected_at_utc=datetime.now(timezone.utc),
    )


def test_playground_api_history_routes_and_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "on.db"))
    monkeypatch.setenv("KURO_PLAYGROUND_ENABLED", "true")
    monkeypatch.setenv("KURO_PLAYGROUND_API_ENABLED", "true")
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())
    monkeypatch.setattr(service.router, "invoke_single", lambda provider_id, req: _response(provider_id, "ok"))

    app = FastAPI()
    app.include_router(create_playground_router(service=service, admin_dependency=_admin_dependency))
    client = TestClient(app)

    forbidden = client.get("/api/playground/sessions")
    assert forbidden.status_code == 403

    latest_empty = client.get("/api/playground/sessions/latest", headers={"x-admin": "1"})
    assert latest_empty.status_code == 404

    invalid_custom = client.post(
        "/api/playground/sessions",
        headers={"x-admin": "1"},
        json={"mode": "research", "session_id": "bad id with spaces"},
    )
    assert invalid_custom.status_code == 422

    created = client.post(
        "/api/playground/sessions",
        headers={"x-admin": "1"},
        json={"mode": "research", "session_id": "route-session-01"},
    )
    assert created.status_code == 200
    assert created.json()["reconnected"] is False
    sid = created.json()["session_id"]

    created_again = client.post(
        "/api/playground/sessions",
        headers={"x-admin": "1"},
        json={"mode": "research", "session_id": "route-session-01"},
    )
    assert created_again.status_code == 200
    assert created_again.json()["reconnected"] is True

    latest = client.get("/api/playground/sessions/latest", headers={"x-admin": "1"})
    assert latest.status_code == 200
    assert latest.json()["session_id"] == sid

    listed = client.get("/api/playground/sessions?limit=20", headers={"x-admin": "1"})
    assert listed.status_code == 200
    assert len(listed.json()["sessions"]) >= 1

    executed = client.post(
        "/api/playground/executions",
        headers={"x-admin": "1"},
        json={"session_id": sid, "provider_id": "openai", "prompt": "hello"},
    )
    assert executed.status_code == 200
    execution_id = executed.json()["execution_id"]

    history = client.get(f"/api/playground/sessions/{sid}/history", headers={"x-admin": "1"})
    assert history.status_code == 200
    assert history.json()["session"]["session_id"] == sid
    assert len(history.json()["executions"]) >= 1

    missing_exec_arg = client.get(
        f"/api/playground/sessions/{sid}/artifacts/json?type=execution_raw",
        headers={"x-admin": "1"},
    )
    assert missing_exec_arg.status_code == 422

    session_artifact = client.get(
        f"/api/playground/sessions/{sid}/artifacts/json?type=session",
        headers={"x-admin": "1"},
    )
    assert session_artifact.status_code == 200
    assert "attachment;" in (session_artifact.headers.get("content-disposition") or "").lower()

    raw_artifact = client.get(
        f"/api/playground/sessions/{sid}/artifacts/json?type=execution_raw&execution_id={execution_id}",
        headers={"x-admin": "1"},
    )
    assert raw_artifact.status_code == 200
    assert "application/json" in (raw_artifact.headers.get("content-type") or "")

    trace_artifact = client.get(
        f"/api/playground/sessions/{sid}/artifacts/json?type=execution_trace&execution_id={execution_id}",
        headers={"x-admin": "1"},
    )
    assert trace_artifact.status_code == 200

    missing_session_history = client.get(
        "/api/playground/sessions/unknown/history",
        headers={"x-admin": "1"},
    )
    assert missing_session_history.status_code == 404
