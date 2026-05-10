"""RBAC hardening tests for admin-only routes.

--- Header Doc ---
Purpose: Ensure non-admin tokens are blocked from ingestion/admin-only APIs.
Caller: pytest Batch-3 hardening gate.
Dependencies: fastapi.testclient, main app routing.
Main Functions: test_ingestion_routes_forbid_non_admin,
                test_openclaw_skills_route_admin_only,
                test_api_me_returns_user_profile.
Side Effects: Uses monkeypatch for auth resolution and OpenClaw bridge stubs.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

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

import main


def _auth_client(monkeypatch, username: str) -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def _request(client: TestClient, method: str, path: str, **kwargs):
    cookies = {main.COOKIE_NAME: "Bearer dummy"}
    method_upper = method.upper()
    if method_upper == "GET":
        return client.get(path, cookies=cookies, **kwargs)
    if method_upper == "POST":
        return client.post(path, cookies=cookies, **kwargs)
    if method_upper == "PUT":
        return client.put(path, cookies=cookies, **kwargs)
    if method_upper == "DELETE":
        return client.delete(path, cookies=cookies, **kwargs)
    raise ValueError(f"Unsupported method: {method}")


def test_ingestion_routes_forbid_non_admin(monkeypatch):
    client = _auth_client(monkeypatch, username="Faikhira")

    routes = [
        ("GET", "/api/ingestion/datasets", {}),
        ("GET", "/api/ingestion/datasets/ds-1", {}),
        ("GET", "/api/ingestion/datasets/ds-1/chunks", {}),
        ("GET", "/api/ingestion/datasets/ds-1/lineage", {}),
        ("GET", "/api/ingestion/jobs", {}),
        ("GET", "/api/ingestion/search", {"params": {"q": "test"}}),
        ("GET", "/api/ingestion/analytics/overview", {}),
        ("GET", "/api/ingestion/analytics/retrieval", {}),
        ("GET", "/api/ingestion/logs", {}),
        ("GET", "/api/ingestion/chroma/health", {}),
        ("GET", "/api/ingestion/graph/ds-1", {}),
        ("POST", "/api/ingestion/upload", {
            "files": {"file": ("sample.txt", b"hello", "text/plain")},
            "data": {"category": "general", "tags": "", "memory_scope": "chroma_only", "source_type": ""},
        }),
        ("POST", "/api/ingestion/datasets/ds-1/reindex", {}),
        ("GET", "/api/ingestion/orphan-sources", {}),
        ("POST", "/api/ingestion/orphan-sources/reingest", {
            "json": {
                "filenames": ["orphan.txt"],
                "category": "recovered",
                "tags": "recovered,orphan-source",
                "memory_scope": "chroma_only",
            }
        }),
        ("POST", "/api/ingestion/datasets/ds-1/archive", {}),
        ("POST", "/api/ingestion/datasets/ds-1/delete", {}),
        ("POST", "/api/ingestion/chroma/cleanup-orphans", {}),
    ]

    for method, path, kwargs in routes:
        response = _request(client, method, path, **kwargs)
        assert response.status_code == 403, f"Expected 403 for {method} {path}, got {response.status_code}"


def test_openclaw_skills_route_admin_only(monkeypatch):
    from kuro_backend.execution import openclaw_bridge

    async def _fake_list_available_skills():
        return [{"name": "skill_a"}]

    monkeypatch.setattr(openclaw_bridge, "list_available_skills", _fake_list_available_skills)
    monkeypatch.setattr(openclaw_bridge, "get_circuit_state", lambda: "closed")

    admin_client = _auth_client(monkeypatch, username="Pantronux")
    admin_response = admin_client.get("/api/openclaw/skills", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert admin_response.status_code == 200
    body = admin_response.json()
    assert body["circuit_breaker_state"] == "closed"
    assert body["skills"] == [{"name": "skill_a"}]

    non_admin_client = _auth_client(monkeypatch, username="Faikhira")
    non_admin_response = non_admin_client.get("/api/openclaw/skills", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert non_admin_response.status_code == 403


def test_api_me_returns_user_profile(monkeypatch):
    client = _auth_client(monkeypatch, username="Faikhira")
    response = client.get("/api/me", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "Faikhira"
    assert body["is_admin"] is False
