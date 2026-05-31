from __future__ import annotations

from fastapi.testclient import TestClient

import main


def _auth_client() -> TestClient:
    client = TestClient(main.app)
    client.cookies.set(main.COOKIE_NAME, "Bearer dummy")
    return client


def test_kcc_command_center_forbidden_for_non_admin(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "kcc")
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": "Faikhira"})
    monkeypatch.setattr(main.auth_db, "get_user", lambda _username: {"display_name": "Faikhira", "role": "User"})

    response = _auth_client().get("/command-center")

    assert response.status_code == 403


def test_kcc_ingestion_ops_forbidden_for_non_admin(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "kcc")
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": "Faikhira"})

    response = _auth_client().get("/api/kcc/knowledge/ingest/jobs")

    assert response.status_code == 403
