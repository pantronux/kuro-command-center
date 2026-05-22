"""Ollama optional smoke route contract tests."""
from __future__ import annotations

import json
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


class _FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def _auth_client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_admin_ollama_health_route_protected(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_OLLAMA_ENABLED", False, raising=False)

    anonymous = TestClient(main.app)
    assert anonymous.get("/api/admin/providers/ollama/health").status_code == 401

    non_admin = _auth_client(monkeypatch, username="Faikhira")
    assert non_admin.get(
        "/api/admin/providers/ollama/health",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    ).status_code == 403

    admin = _auth_client(monkeypatch, username="Pantronux")
    response = admin.get(
        "/api/admin/providers/ollama/health",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["provider"] == "ollama"
    assert body["data"]["status"] == "disabled"


def test_admin_ollama_smoke_test_disabled_is_safe(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_OLLAMA_ENABLED", False, raising=False)
    client = _auth_client(monkeypatch)

    response = client.post(
        "/api/admin/providers/ollama/smoke-test",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["success"] is False
    assert body["data"]["error"]["code"] == "provider_unavailable"


def test_admin_ollama_smoke_test_uses_harmless_prompt(monkeypatch):
    from kuro_backend.providers import ollama_provider

    monkeypatch.setattr(main.settings, "KURO_OLLAMA_ENABLED", True, raising=False)
    monkeypatch.setattr(main.settings, "KURO_OLLAMA_BASE_URL", "http://localhost:11434", raising=False)
    monkeypatch.setattr(main.settings, "KURO_MODEL_OLLAMA_LOCAL", "qwen", raising=False)
    seen = {}

    def _fake_urlopen(request, timeout):
        seen["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeHTTPResponse(
            {"model": "qwen", "message": {"role": "assistant", "content": "ok"}, "done": True}
        )

    monkeypatch.setattr(ollama_provider.urllib.request, "urlopen", _fake_urlopen)
    client = _auth_client(monkeypatch)

    response = client.post(
        "/api/admin/providers/ollama/smoke-test",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["success"] is True
    assert body["data"]["provider"] == "ollama"
    assert seen["payload"]["messages"] == [
        {"role": "user", "content": "Reply with exactly: ok"}
    ]
