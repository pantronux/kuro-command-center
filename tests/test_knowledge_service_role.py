from __future__ import annotations

from fastapi.testclient import TestClient

import main


def _client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_knowledge_role_exposes_health_but_not_ui(monkeypatch, tmp_path):
    monkeypatch.setenv("KURO_APP_ROLE", "knowledge")
    monkeypatch.setenv("KURO_KNOWLEDGE_DB_PATH", str(tmp_path / "knowledge.db"))
    client = _client(monkeypatch)

    assert client.get("/api/knowledge/health").status_code == 200
    assert client.get("/krc-shell", cookies={main.COOKIE_NAME: "Bearer dummy"}).status_code == 404
    assert client.get("/command-center", cookies={main.COOKIE_NAME: "Bearer dummy"}).status_code == 404
    assert client.get("/", cookies={main.COOKIE_NAME: "Bearer dummy"}).status_code == 404


def test_knowledge_ingest_jobs_require_auth_or_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("KURO_KNOWLEDGE_DB_PATH", str(tmp_path / "knowledge.db"))

    unauth = TestClient(main.app).get("/api/knowledge/ingest/jobs")
    assert unauth.status_code == 401

    authed = _client(monkeypatch).post(
        "/api/knowledge/ingest",
        json={"source_app": "krc", "title": "Paper", "content": "body"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert authed.status_code == 200
    job_id = authed.json()["job"]["job_id"]

    detail = _client(monkeypatch).get(
        f"/api/knowledge/ingest/jobs/{job_id}",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert detail.status_code == 200
    assert detail.json()["job"]["status"] == "queued"
