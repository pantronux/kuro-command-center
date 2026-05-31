from __future__ import annotations

from pathlib import Path

from kuro_backend.integrations.kuro_stack_client import KuroStackKnowledgeClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_stack_contract_doc_forbids_direct_db_sharing():
    doc = (PROJECT_ROOT / "docs/integrations/kuro_stack_contract.md").read_text(encoding="utf-8")

    assert "HTTP APIs only" in doc
    assert "Direct reads of KRC chat history" in doc
    assert "Shared SQLite DB access" in doc
    assert "Direct writes to canonical research memory" in doc


def test_stack_client_uses_http_api(monkeypatch):
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    def _post(url, **kwargs):
        calls.append((url, kwargs))
        return _Response()

    monkeypatch.setattr("kuro_backend.integrations.kuro_stack_client.requests.post", _post)

    client = KuroStackKnowledgeClient(base_url="http://knowledge.local", api_key="key")
    payload = client.search_approved(query="novelty")

    assert payload == {"results": []}
    assert calls[0][0] == "http://knowledge.local/api/knowledge/search-approved"
    assert calls[0][1]["headers"]["X-Kuro-Knowledge-Key"] == "key"
