from __future__ import annotations

from fastapi.testclient import TestClient

import main


def test_kcc_does_not_serve_research_surfaces(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "kcc")
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": "Pantronux"})

    client = TestClient(main.app)
    cookies = {main.COOKIE_NAME: "Bearer dummy"}

    assert client.get("/research", cookies=cookies).status_code == 404
    assert client.get("/krc-shell", cookies=cookies).status_code == 404
    assert client.get("/api/research/projects", cookies=cookies).status_code == 404


def test_kcc_shell_does_not_expose_research_history(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "kcc")
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": "Pantronux"})
    monkeypatch.setattr(main.auth_db, "get_user", lambda _username: {"display_name": "Pantronux", "role": "User"})

    response = TestClient(main.app).get(
        "/command-center",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    assert "PhD Advisor" not in response.text
    assert "Research Console" not in response.text
    assert "raw KRC research history" not in response.text
