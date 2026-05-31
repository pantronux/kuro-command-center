from __future__ import annotations

from fastapi.testclient import TestClient

import main
from kuro_backend.integrations.kuro_stack_client import KuroStackKnowledgeClient


def test_kcc_knowledge_client_lists_ingest_jobs_by_http(monkeypatch):
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"jobs": []}

    def _get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response()

    monkeypatch.setattr("kuro_backend.integrations.kuro_stack_client.requests.get", _get)

    payload = KuroStackKnowledgeClient(base_url="http://knowledge.local", api_key="key").list_ingest_jobs(limit=10)

    assert payload == {"jobs": []}
    assert calls[0][0] == "http://knowledge.local/api/knowledge/ingest/jobs"
    assert calls[0][1]["headers"]["X-Kuro-Knowledge-Key"] == "key"


def test_kcc_ingestion_ops_route_proxies_to_knowledge_api(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "kcc")
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": "Pantronux"})
    calls = []

    def _list_jobs(self, *, limit=50):
        calls.append(limit)
        return {"jobs": [{"job_id": "job_1"}]}

    monkeypatch.setattr(
        "kuro_backend.integrations.kuro_stack_client.KuroStackKnowledgeClient.list_ingest_jobs",
        _list_jobs,
    )

    response = TestClient(main.app).get(
        "/api/kcc/knowledge/ingest/jobs?limit=10",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["jobs"][0]["job_id"] == "job_1"
    assert calls == [10]
