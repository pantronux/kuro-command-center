from __future__ import annotations

import importlib

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from playground_runtime.api.router import create_playground_router
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


def test_playground_api_returns_403_when_flags_off(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "off.db"))
    monkeypatch.setenv("KURO_PLAYGROUND_ENABLED", "false")
    monkeypatch.setenv("KURO_PLAYGROUND_API_ENABLED", "false")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())
    app = FastAPI()
    app.include_router(create_playground_router(service=service, admin_dependency=_admin_dependency))
    client = TestClient(app)

    response = client.get("/api/playground/health", headers={"x-admin": "1"})
    assert response.status_code == 403
    assert "Disabled" in response.json()["detail"]


def test_playground_api_admin_and_happy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "on.db"))
    monkeypatch.setenv("KURO_PLAYGROUND_ENABLED", "true")
    monkeypatch.setenv("KURO_PLAYGROUND_API_ENABLED", "true")
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())
    app = FastAPI()
    app.include_router(create_playground_router(service=service, admin_dependency=_admin_dependency))
    client = TestClient(app)

    forbidden = client.get("/api/playground/health")
    assert forbidden.status_code == 403

    health = client.get("/api/playground/health", headers={"x-admin": "1"})
    assert health.status_code == 200

    created = client.post(
        "/api/playground/sessions",
        headers={"x-admin": "1"},
        json={"mode": "research"},
    )
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    traces = client.get(
        f"/api/playground/sessions/{session_id}/traces",
        headers={"x-admin": "1"},
    )
    assert traces.status_code == 200
    assert traces.json()["traces"] == []
