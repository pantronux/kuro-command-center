"""Frontend V2 feature-flag and template safety tests."""
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


def _client(monkeypatch, username: str = "Pantronux", role: str = "Administrator") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    monkeypatch.setattr(
        main.auth_db,
        "get_user",
        lambda resolved_username: {
            "display_name": resolved_username,
            "role": role,
            "master_name": f"Master {resolved_username}",
            "restricted_persona": "",
            "custom_persona": "",
        },
    )
    return TestClient(main.app)


def _get_index(client: TestClient):
    return client.get("/", cookies={main.COOKIE_NAME: "Bearer dummy"})


def test_index_renders_current_ui_when_flag_false(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_FRONTEND_V2_ENABLED", False, raising=False)
    client = _client(monkeypatch)

    response = _get_index(client)

    assert response.status_code == 200
    assert "Chat with Kuro" in response.text
    assert "glass-sidebar" in response.text
    assert "data-testid=\"frontend-v2-shell\"" not in response.text


def test_index_renders_v2_markers_when_flag_true(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_FRONTEND_V2_ENABLED", True, raising=False)
    client = _client(monkeypatch)

    response = _get_index(client)

    assert response.status_code == 200
    assert "data-kuro-frontend-v2=\"true\"" in response.text
    assert "data-testid=\"frontend-v2-shell\"" in response.text
    assert "/static/js/v2/chat.js" in response.text
    assert "/static/css/v2.css" in response.text


def test_non_admin_does_not_see_administration_settings(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_FRONTEND_V2_ENABLED", True, raising=False)
    client = _client(monkeypatch, username="Faikhira", role="User")

    response = _get_index(client)

    assert response.status_code == 200
    assert "Administration Settings" not in response.text
    assert "data-testid=\"admin-settings-entry\"" not in response.text


def test_admin_sees_administration_settings(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_FRONTEND_V2_ENABLED", True, raising=False)
    client = _client(monkeypatch, username="Pantronux", role="Administrator")

    response = _get_index(client)

    assert response.status_code == 200
    assert "Administration Settings" in response.text
    assert "data-testid=\"admin-settings-entry\"" in response.text
    assert "data-testid=\"admin-settings-modal\"" in response.text


def test_static_js_files_served(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_FRONTEND_V2_ENABLED", True, raising=False)
    client = _client(monkeypatch)
    files = [
        "api.js",
        "chat.js",
        "sidebar.js",
        "profile_menu.js",
        "admin_settings.js",
        "streaming.js",
        "model_settings.js",
        "tasks.js",
        "market.js",
    ]

    for filename in files:
        response = client.get(f"/static/js/v2/{filename}")
        assert response.status_code == 200, filename
        assert "text/javascript" in response.headers.get("content-type", "")


def test_no_raw_secret_values_appear_in_v2_html(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_FRONTEND_V2_ENABLED", True, raising=False)
    monkeypatch.setenv("TELEGRAM_TOKEN", "secret-telegram-token-for-test")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini-key-for-test")
    client = _client(monkeypatch)

    response = _get_index(client)

    assert response.status_code == 200
    assert "secret-telegram-token-for-test" not in response.text
    assert "secret-gemini-key-for-test" not in response.text
    assert "TELEGRAM_TOKEN" not in response.text
    assert "GEMINI_API_KEY" not in response.text


def test_chat_settings_panel_uses_safe_model_aliases(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_FRONTEND_V2_ENABLED", True, raising=False)
    client = _client(monkeypatch)

    response = _get_index(client)

    assert response.status_code == 200
    assert "data-testid=\"safe-model-aliases\"" in response.text
    assert "gemini_fast" in response.text
    assert "openai_nano" in response.text
    assert "api_key" not in response.text.lower()
    assert "secret" not in response.text.lower()


def test_backend_admin_endpoint_still_forbidden_for_non_admin(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_FRONTEND_V2_ENABLED", True, raising=False)
    client = _client(monkeypatch, username="Faikhira", role="User")

    response = client.get(
        "/api/admin/storage/health",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 403
