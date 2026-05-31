from __future__ import annotations

from fastapi.testclient import TestClient

import main


def _client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setenv("KURO_APP_ROLE", "kcc")
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    monkeypatch.setattr(main.auth_db, "get_user", lambda _username: {"display_name": username, "role": "User"})
    client = TestClient(main.app)
    client.cookies.set(main.COOKIE_NAME, "Bearer dummy")
    return client


def test_kcc_command_center_renders_for_admin(monkeypatch):
    response = _client(monkeypatch).get("/command-center")

    assert response.status_code == 200
    html = response.text
    assert "Kuro Command Center" in html
    assert "Market Sentinel" in html
    assert "Telegram Command Center" in html
    assert "Ingestion Operations" in html


def test_kcc_root_redirects_to_command_center(monkeypatch):
    response = _client(monkeypatch).get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/command-center"
