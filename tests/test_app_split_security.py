from __future__ import annotations

from fastapi.testclient import TestClient

import main
from kuro_backend.knowledge_center.candidates import KnowledgeStore


def _client(monkeypatch, username: str) -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    monkeypatch.setattr(main.auth_db, "get_user", lambda _username: {"display_name": username, "role": "User"})
    return TestClient(main.app)


def test_non_admin_cannot_open_kcc(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "kcc")

    response = _client(monkeypatch, "Faikhira").get("/command-center", cookies={main.COOKIE_NAME: "Bearer dummy"})

    assert response.status_code == 403


def test_non_admin_cannot_approve_knowledge(monkeypatch, tmp_path):
    monkeypatch.setenv("KURO_KNOWLEDGE_DB_PATH", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("KURO_KNOWLEDGE_CANDIDATES_ENABLED", "true")
    client = _client(monkeypatch, "Pantronux")
    candidate_id = client.post(
        "/api/knowledge/candidates",
        json={"source_app": "ks", "content": "candidate"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    ).json()["candidate_id"]

    forbidden = _client(monkeypatch, "Faikhira").post(
        f"/api/admin/knowledge/candidates/{candidate_id}/approve",
        json={},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert forbidden.status_code == 403


def test_knowledge_results_do_not_expose_raw_paths_or_content(monkeypatch, tmp_path):
    monkeypatch.setenv("KURO_KNOWLEDGE_DB_PATH", str(tmp_path / "knowledge.db"))
    store = KnowledgeStore(tmp_path / "knowledge.db")
    store.upsert_approved(
        title="Safe result",
        summary="Stored in /home/kuro/private/kuro_chat_history.db with API_KEY=secret",
        content="Raw chat history should not be returned.",
        domain="research",
        source_type="manual",
        source_id="src-1",
    )

    response = _client(monkeypatch, "Pantronux").post(
        "/api/knowledge/search-approved",
        json={"query": "Safe result"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    result = response.json()["results"][0]
    assert "content" not in result
    assert "/home/kuro" not in str(result)
    assert "API_KEY" not in str(result)
