"""Enterprise refactor feature flag baseline tests."""
from __future__ import annotations

import json
import os
import subprocess
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
from kuro_backend import enterprise_flags


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    for flag in enterprise_flags.ENTERPRISE_FLAG_NAMES:
        env[flag] = ""
    for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
        env[key] = ""
    return env


def _auth_client(monkeypatch, username: str) -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_enterprise_flags_default_off():
    code = """
from kuro_backend.enterprise_flags import ENTERPRISE_FLAG_NAMES, is_enabled
assert all(is_enabled(flag) is False for flag in ENTERPRISE_FLAG_NAMES)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=_clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_capabilities_public_safe(monkeypatch):
    for flag in enterprise_flags.ENTERPRISE_FLAG_NAMES:
        monkeypatch.setattr(main.settings, flag, False, raising=False)

    client = TestClient(main.app)
    response = client.get("/api/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["enterprise_refactor_enabled"] is False
    assert body["data"]["features"]["chat"]["available"] is True
    assert body["data"]["features"]["chat"]["v2_enabled"] is False

    public_text = json.dumps(body, sort_keys=True).lower()
    forbidden_fragments = [
        "api_key",
        "secret",
        "password",
        "jwt",
        "prompt_stack",
        "memory_namespace",
        "tool_name",
        "db_path",
        "sqlite",
        "chroma.sqlite",
        "gemini-",
        "gpt-",
        "claude-",
        "deepseek-",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in public_text


def test_admin_enterprise_flags_requires_admin(monkeypatch):
    unauthenticated_client = TestClient(main.app)
    unauthenticated = unauthenticated_client.get("/api/admin/enterprise-flags")
    assert unauthenticated.status_code == 401

    non_admin_client = _auth_client(monkeypatch, username="Faikhira")
    non_admin = non_admin_client.get(
        "/api/admin/enterprise-flags",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert non_admin.status_code == 403

    admin_client = _auth_client(monkeypatch, username="Pantronux")
    admin = admin_client.get(
        "/api/admin/enterprise-flags",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert admin.status_code == 200
    body = admin.json()
    assert body["status"] == "success"
    assert "flags" in body["data"]
    assert "providers" in body["data"]
    assert "GEMINI_API_KEY" not in json.dumps(body)


def test_missing_provider_keys_do_not_break_startup():
    code = """
from kuro_backend.config import settings
from kuro_backend.enterprise_flags import get_enterprise_flag_snapshot

snapshot = get_enterprise_flag_snapshot(admin=True)
assert settings.GEMINI_API_KEY in (None, "")
assert settings.OPENAI_API_KEY == ""
assert settings.ANTHROPIC_API_KEY == ""
assert settings.DEEPSEEK_API_KEY == ""
assert all(provider["configured"] is False for provider in snapshot["providers"].values())
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=_clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
