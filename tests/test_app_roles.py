from __future__ import annotations

from fastapi.testclient import TestClient

import main
from kuro_backend.app_roles import get_app_role, get_app_role_snapshot, is_kcc_role, is_knowledge_role, is_krc_role


def _client_as(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_default_role_is_legacy(monkeypatch):
    monkeypatch.delenv("KURO_APP_ROLE", raising=False)
    monkeypatch.delenv("KURO_APP_PROFILE", raising=False)

    assert get_app_role() == "legacy"
    assert get_app_role_snapshot(public=True)["workspace_label"] == "Kuro AI"


def test_kuro_app_role_overrides_compat_profile(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "legacy")
    monkeypatch.setenv("KURO_APP_ROLE", "kcc")

    assert get_app_role() == "kcc"
    assert is_kcc_role() is True
    assert is_krc_role() is False


def test_profile_krc_still_maps_to_krc_role(monkeypatch):
    monkeypatch.delenv("KURO_APP_ROLE", raising=False)
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")

    assert get_app_role() == "krc"
    assert is_krc_role() is True


def test_knowledge_and_invalid_roles(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "knowledge")
    assert is_knowledge_role() is True

    monkeypatch.setenv("KURO_APP_ROLE", "unknown")
    assert get_app_role() == "legacy"


def test_admin_app_role_route_requires_admin(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "krc")

    forbidden = _client_as(monkeypatch, "Faikhira").get(
        "/api/admin/app-role",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert forbidden.status_code == 403

    response = _client_as(monkeypatch, "Pantronux").get(
        "/api/admin/app-role",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["app_role"] == "krc"
    assert "supported_roles" in data
