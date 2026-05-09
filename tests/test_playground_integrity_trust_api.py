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


def test_integrity_trust_workflow_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "kuro_playground.db"))
    monkeypatch.setenv("KURO_PLAYGROUND_ENABLED", "true")
    monkeypatch.setenv("KURO_PLAYGROUND_API_ENABLED", "true")
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())
    monkeypatch.setattr(service.router, "invoke_single", lambda provider_id, req: _response(provider_id, "ok"))

    app = FastAPI()
    app.include_router(create_playground_router(service=service, admin_dependency=_admin_dependency))
    client = TestClient(app)

    created = client.post("/api/playground/sessions", headers={"x-admin": "1"}, json={"mode": "forensic"})
    assert created.status_code == 200
    sid = created.json()["session_id"]

    executed = client.post(
        "/api/playground/executions",
        headers={"x-admin": "1"},
        json={"session_id": sid, "provider_id": "openai", "prompt": "trust"},
    )
    assert executed.status_code == 200
    execution_id = executed.json()["execution_id"]

    snapshot = client.post(
        "/api/playground/snapshots",
        headers={"x-admin": "1"},
        json={"session_id": sid, "execution_id": execution_id},
    )
    assert snapshot.status_code == 200
    snapshot_id = snapshot.json()["snapshot_id"]

    overview = client.get(
        f"/api/playground/sessions/{sid}/integrity-overview?workflow_mode=deep",
        headers={"x-admin": "1"},
    )
    assert overview.status_code == 200
    assert overview.json()["workflow_mode"] == "deep"

    detail = client.get(
        f"/api/playground/sessions/{sid}/executions/{execution_id}/integrity-detail",
        headers={"x-admin": "1"},
    )
    assert detail.status_code == 200
    assert detail.json()["execution_id"] == execution_id

    refreshed = client.post(
        f"/api/playground/sessions/{sid}/integrity/refresh",
        headers={"x-admin": "1"},
        json={"workflow_mode": "academic"},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["overview"]["workflow_mode"] == "academic"

    verified = client.post(
        f"/api/playground/snapshots/{snapshot_id}/verify",
        headers={"x-admin": "1"},
        json={"session_id": sid},
    )
    assert verified.status_code == 200

    trust = client.get(
        f"/api/playground/snapshots/{snapshot_id}/trust-summary?session_id={sid}",
        headers={"x-admin": "1"},
    )
    assert trust.status_code == 200
    assert trust.json()["snapshot_id"] == snapshot_id

    lineage = client.get(f"/api/playground/sessions/{sid}/lineage", headers={"x-admin": "1"})
    assert lineage.status_code == 200
    assert isinstance(lineage.json().get("nodes"), list)

    exported = client.post(
        f"/api/playground/sessions/{sid}/exports/forensic-bundle",
        headers={"x-admin": "1"},
        json={},
    )
    assert exported.status_code == 200
    assert exported.json()["bundle"]["bundle_sha256"]

    forensic_view = client.get(
        f"/api/playground/sessions/{sid}/forensic-view?view=summary&workflow_mode=academic",
        headers={"x-admin": "1"},
    )
    assert forensic_view.status_code == 200
    assert forensic_view.json()["workflow_mode"] == "academic"

    history = client.get(f"/api/playground/sessions/{sid}/history", headers={"x-admin": "1"})
    assert history.status_code == 200
    payload = history.json()
    assert "integrity_overview" in payload
    assert "session_timeline_integrity" in payload
    assert "execution_integrity_rows" in payload
    assert "snapshot_trust_rows" in payload
