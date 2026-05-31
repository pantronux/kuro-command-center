from __future__ import annotations

from fastapi.testclient import TestClient

import main


def _client(monkeypatch, username: str) -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    monkeypatch.setattr(main.auth_db, "get_user", lambda _username: {"display_name": username, "role": "Administrator"})
    return TestClient(main.app)


def test_command_center_requires_kcc_role(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "legacy")
    response = _client(monkeypatch, "Pantronux").get("/command-center", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 404


def test_command_center_requires_admin(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "kcc")
    response = _client(monkeypatch, "Faikhira").get("/command-center", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 403


def test_command_center_shows_ops_and_hides_research(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "kcc")
    response = _client(monkeypatch, "Pantronux").get("/command-center", cookies={main.COOKIE_NAME: "Bearer dummy"})

    assert response.status_code == 200
    html = response.text
    assert "Kuro Command Center" in html
    assert "Market Sentinel" in html
    assert "Telegram Command Center" in html
    assert "Ingestion Operations" in html
    assert "Literature Library" not in html
