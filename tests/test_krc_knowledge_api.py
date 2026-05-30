from __future__ import annotations

import os
import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WORKING_DIR", str(PROJECT_ROOT))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *args, **kwargs):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

if "phoenix" not in sys.modules:
    fake_phoenix = types.ModuleType("phoenix")

    class _FakePhoenixApp:
        url = "http://localhost:6006"

        def close(self):
            return None

    fake_phoenix.launch_app = lambda *args, **kwargs: _FakePhoenixApp()
    sys.modules["phoenix"] = fake_phoenix

import main
from kuro_backend.knowledge_center.candidates import KnowledgeStore


def _client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def _use_knowledge_db(monkeypatch, tmp_path: Path) -> KnowledgeStore:
    db_path = tmp_path / "kuro_knowledge_center.db"
    monkeypatch.setenv("KURO_KNOWLEDGE_DB_PATH", str(db_path))
    store = KnowledgeStore(db_path)
    store.init_db()
    return store


def test_knowledge_health_is_public_and_safe(monkeypatch, tmp_path):
    _use_knowledge_db(monkeypatch, tmp_path)
    client = TestClient(main.app)

    response = client.get("/api/knowledge/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["approved_only"] is True
    assert body["candidate_writes_enabled"] is False


def test_search_approved_requires_auth_or_api_key(monkeypatch, tmp_path):
    _use_knowledge_db(monkeypatch, tmp_path)
    client = TestClient(main.app)

    response = client.post("/api/knowledge/search-approved", json={"query": "research"})

    assert response.status_code == 401


def test_search_approved_returns_redacted_approved_results(monkeypatch, tmp_path):
    store = _use_knowledge_db(monkeypatch, tmp_path)
    store.upsert_approved(
        title="Kuro Playground research direction",
        summary="Kuro Playground is primary. API_KEY=secret",
        content="KRC owns research Playground details from /home/kuro/private/kuro_chat_history.db.",
        domain="playground",
        source_type="manual_review",
        source_id="source-playground-1",
        confidence=0.86,
        approved_by="Pantronux",
    )
    client = _client(monkeypatch)

    response = client.post(
        "/api/knowledge/search-approved",
        json={"query": "Kuro Playground", "domains": ["playground"]},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["results"]
    result = body["results"][0]
    assert result["knowledge_id"].startswith("kn_")
    assert result["domain"] == "playground"
    assert "API_KEY" not in result["summary"]
    assert "/home/kuro" not in str(result)
    assert "kuro_chat_history.db" not in str(result)
    assert "content" not in result


def test_search_approved_accepts_knowledge_api_key(monkeypatch, tmp_path):
    _use_knowledge_db(monkeypatch, tmp_path)
    monkeypatch.setenv("KURO_KNOWLEDGE_API_KEY", "test-knowledge-key")
    client = TestClient(main.app)

    response = client.post(
        "/api/knowledge/search-approved",
        json={"query": "anything"},
        headers={"X-Kuro-Knowledge-Key": "test-knowledge-key"},
    )

    assert response.status_code == 200
    assert response.json()["results"] == []


def test_candidate_write_disabled_by_default(monkeypatch, tmp_path):
    _use_knowledge_db(monkeypatch, tmp_path)
    monkeypatch.delenv("KURO_KRC_KNOWLEDGE_CANDIDATES_ENABLED", raising=False)
    client = _client(monkeypatch)

    response = client.post(
        "/api/knowledge/candidates",
        json={
            "source_app": "ks",
            "domain": "research",
            "content": "Candidate should not write by default.",
            "reason": "test",
        },
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 403


def test_candidate_review_promotes_only_after_admin_approval(monkeypatch, tmp_path):
    _use_knowledge_db(monkeypatch, tmp_path)
    monkeypatch.setenv("KURO_KRC_KNOWLEDGE_CANDIDATES_ENABLED", "true")
    client = _client(monkeypatch)

    submitted = client.post(
        "/api/knowledge/candidates",
        json={
            "source_app": "ks",
            "source_chat_id": "ks-chat-1",
            "domain": "playground",
            "title": "Playground note",
            "content": "Kuro Playground remains the primary KRC surface.",
            "reason": "daily chat surfaced durable product knowledge",
        },
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert submitted.status_code == 200
    candidate_id = submitted.json()["candidate_id"]
    assert submitted.json()["canonical"] is False

    pending_search = client.post(
        "/api/knowledge/search-approved",
        json={"query": "primary KRC surface"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert pending_search.status_code == 200
    assert pending_search.json()["results"] == []

    approved = client.post(
        f"/api/admin/knowledge/candidates/{candidate_id}/approve",
        json={
            "summary": "Kuro Playground remains the primary KRC surface.",
            "confidence": 0.91,
        },
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    promoted_search = client.post(
        "/api/knowledge/search-approved",
        json={"query": "primary KRC surface", "domains": ["playground"]},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert promoted_search.status_code == 200
    results = promoted_search.json()["results"]
    assert len(results) == 1
    assert results[0]["source_id"] == candidate_id


def test_source_endpoint_returns_only_approved_metadata(monkeypatch, tmp_path):
    store = _use_knowledge_db(monkeypatch, tmp_path)
    store.upsert_approved(
        title="Architecture split",
        summary="KS and KRC keep separate databases.",
        content="KS does not read KRC raw chat history.",
        domain="architecture",
        source_type="manual_review",
        source_id="arch-source-1",
        confidence=0.9,
        citations=[{"label": "review"}],
        approved_by="Pantronux",
    )
    client = _client(monkeypatch)

    response = client.get(
        "/api/knowledge/sources/arch-source-1",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    source = response.json()["source"]
    assert source["source_id"] == "arch-source-1"
    assert source["source_type"] == "manual_review"
    assert source["knowledge_ids"]
    assert "raw" not in str(source).lower()
