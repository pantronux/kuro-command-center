from __future__ import annotations

from fastapi.testclient import TestClient

import main


def _client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def _cookies():
    return {main.COOKIE_NAME: "Bearer dummy"}


def test_krc_research_ingest_creates_source_and_knowledge_job(monkeypatch, tmp_path):
    monkeypatch.setenv("KURO_RESEARCH_DB_PATH", str(tmp_path / "research.db"))
    monkeypatch.setenv("KURO_KNOWLEDGE_DB_PATH", str(tmp_path / "knowledge.db"))
    client = _client(monkeypatch)

    project_id = client.post(
        "/api/research/projects",
        json={"title": "Ingest project"},
        cookies=_cookies(),
    ).json()["project"]["project_id"]

    response = client.post(
        "/api/research/ingest",
        json={
            "project_id": project_id,
            "title": "Runtime provenance paper",
            "content": "paper body",
            "metadata": {"venue": "TestConf"},
        },
        cookies=_cookies(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"]["project_id"] == project_id
    assert body["knowledge_ingest_job"]["status"] == "queued"

    jobs = client.get("/api/knowledge/ingest/jobs", cookies=_cookies()).json()["jobs"]
    assert jobs[0]["source_app"] == "krc"


def test_knowledge_ingest_retry_is_admin_only(monkeypatch, tmp_path):
    monkeypatch.setenv("KURO_KNOWLEDGE_DB_PATH", str(tmp_path / "knowledge.db"))
    client = _client(monkeypatch, "Pantronux")
    job_id = client.post(
        "/api/knowledge/ingest",
        json={"source_app": "krc", "title": "Paper", "content": "body"},
        cookies=_cookies(),
    ).json()["job"]["job_id"]

    forbidden = _client(monkeypatch, "Faikhira").post(
        f"/api/knowledge/ingest/jobs/{job_id}/retry",
        cookies=_cookies(),
    )
    assert forbidden.status_code == 403

    allowed = _client(monkeypatch, "Pantronux").post(
        f"/api/knowledge/ingest/jobs/{job_id}/retry",
        cookies=_cookies(),
    )
    assert allowed.status_code == 200
    assert allowed.json()["job"]["status"] == "retrying"
