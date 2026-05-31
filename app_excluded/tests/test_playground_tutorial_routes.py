from __future__ import annotations

import os
import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("WORKING_DIR", str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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


def _auth_client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_playground_tutorial_route_allows_pantronux(monkeypatch):
    client = _auth_client(monkeypatch, username="Pantronux")
    response = client.get("/playground/tutorial", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    assert "Kuro Playground | Private Documentation" in response.text


def test_playground_tutorial_route_forbids_non_pantronux(monkeypatch):
    client = _auth_client(monkeypatch, username="Faikhira")
    response = client.get("/playground/tutorial", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 403


def test_playground_tutorial_content_returns_private_markdown(monkeypatch):
    client = _auth_client(monkeypatch, username="Pantronux")
    response = client.get("/api/playground/tutorial/content", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "SYSTEM_MAP_PLAYGROUND" in data["markdown"]
    assert "/playground/tutorial" in data["markdown"]


def test_playground_tutorial_content_forbids_non_pantronux(monkeypatch):
    client = _auth_client(monkeypatch, username="Faikhira")
    response = client.get("/api/playground/tutorial/content", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 403


def test_playground_tutorial_content_returns_404_when_markdown_missing(monkeypatch):
    client = _auth_client(monkeypatch, username="Pantronux")
    target = Path("playground_runtime/SYSTEM_MAP_PLAYGROUND.md")
    original = target.read_text(encoding="utf-8")
    try:
        target.unlink()
        response = client.get("/api/playground/tutorial/content", cookies={main.COOKIE_NAME: "Bearer dummy"})
        assert response.status_code == 404
        assert response.json()["status"] == "error"
    finally:
        target.write_text(original, encoding="utf-8")


def test_main_tutorial_content_route_still_reads_system_map(monkeypatch):
    client = _auth_client(monkeypatch, username="Pantronux")
    response = client.get("/api/tutorial/content", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "SYSTEM_MAP" in data["markdown"]
