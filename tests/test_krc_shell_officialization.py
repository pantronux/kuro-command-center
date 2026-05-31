from __future__ import annotations

from fastapi.testclient import TestClient

import main


def _client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    monkeypatch.setattr(main.auth_db, "get_user", lambda _username: {"display_name": username, "role": "Administrator"})
    return TestClient(main.app)


def test_research_alias_works_only_in_krc_role(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "legacy")
    legacy = _client(monkeypatch).get("/research", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert legacy.status_code == 404

    monkeypatch.setenv("KURO_APP_ROLE", "krc")
    response = _client(monkeypatch).get("/research", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    assert "PhD Research Workspace" in response.text


def test_krc_shell_keeps_compatibility_path_and_hides_legacy_chat(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "krc")
    monkeypatch.delenv("KURO_KRC_LEGACY_CHAT_VISIBLE", raising=False)

    response = _client(monkeypatch).get("/krc-shell", cookies={main.COOKIE_NAME: "Bearer dummy"})

    assert response.status_code == 200
    assert 'data-krc-shell-route="/krc-shell"' in response.text
    assert "Legacy Chat" not in response.text
    assert "Kuro Playground" not in response.text
