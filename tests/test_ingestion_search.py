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
from kuro_backend.ingestion_center import ingestion_manager


def _auth_client(monkeypatch, username="Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    monkeypatch.setattr(
        ingestion_manager,
        "schedule_ingestion_job",
        lambda background_tasks, job_id: ingestion_manager.process_ingestion_job(job_id),
    )
    return TestClient(main.app)


def test_search_matches_dataset_name_and_chunk(monkeypatch):
    client = _auth_client(monkeypatch)
    client.post(
        "/api/ingestion/upload",
        files={"file": ("governance.txt", b"Knowledge governance testing document for sovereign search.")},
        data={"category": "policy", "tags": "governance,policy", "memory_scope": "chroma_only"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    response = client.get("/api/ingestion/search?q=governance", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    assert response.json()["data"]
    assert "governance" in response.json()["data"][0]["dataset_name"].lower()
