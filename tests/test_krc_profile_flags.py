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
from kuro_backend.krc_profile import (
    get_app_profile,
    get_krc_profile_snapshot,
    is_krc_feature_enabled,
    is_krc_profile,
)


def _client_as(monkeypatch, username: str) -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_kuro_app_profile_defaults_to_legacy(monkeypatch):
    monkeypatch.delenv("KURO_APP_PROFILE", raising=False)

    assert get_app_profile() == "legacy"
    assert is_krc_profile() is False
    assert is_krc_feature_enabled("playground") is False


def test_krc_profile_enables_core_features_and_hides_daily_defaults(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    monkeypatch.delenv("KURO_KRC_MARKET_ENABLED", raising=False)

    snapshot = get_krc_profile_snapshot(public=True)

    assert snapshot["app_profile"] == "krc"
    assert snapshot["workspace_label"] == "Kuro Research Center"
    assert snapshot["features"]["playground"] is True
    assert snapshot["features"]["qa_playground"] is False
    assert snapshot["features"]["qa_productization"] is False
    assert snapshot["features"]["evaluation"] is False
    assert snapshot["features"]["export"] is True
    assert snapshot["features"]["market"] is False
    assert snapshot["features"]["telegram_center"] is True
    assert is_krc_feature_enabled("telegram") is True


def test_krc_optional_feature_can_be_enabled_by_flag(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    monkeypatch.setenv("KURO_KRC_MARKET_ENABLED", "true")
    monkeypatch.setenv("KURO_KRC_QA_PLAYGROUND_ENABLED", "true")
    monkeypatch.setenv("KURO_KRC_EVALUATION_ENABLED", "true")

    assert is_krc_feature_enabled("market_sentinel") is True
    assert is_krc_feature_enabled("qa") is True
    assert is_krc_feature_enabled("evaluation") is True


def test_admin_krc_profile_requires_admin(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")

    non_admin = _client_as(monkeypatch, "Faikhira")
    forbidden = non_admin.get(
        "/api/admin/krc/profile",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert forbidden.status_code == 403

    admin = _client_as(monkeypatch, "Pantronux")
    response = admin.get(
        "/api/admin/krc/profile",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["app_profile"] == "krc"
    assert "raw_flags" in body["data"]


def test_public_capabilities_include_safe_profile(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    client = TestClient(main.app)

    response = client.get("/api/capabilities")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["app_profile"] == "krc"
    assert data["krc"]["workspace_label"] == "Kuro Research Center"
    assert "raw_flags" not in data["krc"]
