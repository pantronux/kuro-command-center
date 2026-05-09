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


def _auth_client(monkeypatch, username="Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_ingestion_pages_load_for_admin(monkeypatch):
    client = _auth_client(monkeypatch)
    response = client.get("/ingestion", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    assert "Sovereign Knowledge" in response.text

    response = client.get("/ingestion/analytics", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    assert "Ingestion Analytics" in response.text

    response = client.get("/ingestion/logs", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    assert "Ingestion Logs" in response.text

    response = client.get("/api/ingestion/logs", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    assert response.json().get("status") == "success"


def test_ingestion_admin_routes_reject_non_admin(monkeypatch):
    client = _auth_client(monkeypatch, username="Faikhira")
    response = client.get("/api/ingestion/datasets", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 403
    response = client.get("/api/ingestion/logs", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 403
