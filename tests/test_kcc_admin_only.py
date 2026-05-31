from __future__ import annotations

from fastapi.testclient import TestClient

import main


def test_kcc_command_center_forbidden_for_non_admin(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "kcc")
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": "Faikhira"})
    monkeypatch.setattr(main.auth_db, "get_user", lambda _username: {"display_name": "Faikhira", "role": "User"})

    response = TestClient(main.app).get(
        "/command-center",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 403


def test_kcc_ingestion_ops_forbidden_for_non_admin(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "kcc")
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": "Faikhira"})

    response = TestClient(main.app).get(
        "/api/kcc/knowledge/ingest/jobs",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 403
