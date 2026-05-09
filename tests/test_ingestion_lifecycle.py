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
from kuro_backend.ingestion_center import embedding_manager, ingestion_manager


def _auth_client(monkeypatch, username="Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    monkeypatch.setattr(
        ingestion_manager,
        "schedule_ingestion_job",
        lambda background_tasks, job_id: ingestion_manager.process_ingestion_job(job_id),
    )
    return TestClient(main.app)


def _upload_dataset(client: TestClient, name: str, content: bytes):
    response = client.post(
        "/api/ingestion/upload",
        files={"file": (name, content, "text/plain")},
        data={"category": "notes", "tags": "ai,tests", "memory_scope": "chroma_only"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert response.status_code == 202, response.text
    dataset_uuid = response.json()["data"]["dataset"]["dataset_uuid"]
    detail = client.get(f"/api/ingestion/datasets/{dataset_uuid}", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert detail.status_code == 200
    return detail.json()["data"]["dataset"]


def test_upload_reindex_archive_delete_flow(monkeypatch):
    client = _auth_client(monkeypatch)
    dataset = _upload_dataset(client, "alpha.txt", b"Alpha Beta Gamma\n\nPantronux Dataset Example")
    assert dataset["ingestion_status"] in {"completed", "partially_indexed"}

    dataset_uuid = dataset["dataset_uuid"]
    detail = client.get(f"/api/ingestion/datasets/{dataset_uuid}", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert detail.status_code == 200
    payload = detail.json()["data"]
    assert payload["chunks"]

    response = client.post(f"/api/ingestion/datasets/{dataset_uuid}/reindex", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 202
    assert response.json()["data"]["dataset"]["ingestion_status"] in {"completed", "partially_indexed"}

    response = client.post(f"/api/ingestion/datasets/{dataset_uuid}/archive", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    assert response.json()["data"]["dataset"]["ingestion_status"] == "archived"

    response = client.get("/api/ingestion/datasets?active_only=true", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert all(item["dataset_uuid"] != dataset_uuid for item in response.json()["data"]["datasets"])

    response = client.post(f"/api/ingestion/datasets/{dataset_uuid}/delete", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    assert response.json()["data"]["dataset"]["ingestion_status"] == "deleted"

    lineage = client.get(f"/api/ingestion/datasets/{dataset_uuid}/lineage", cookies={main.COOKIE_NAME: "Bearer dummy"})
    ops = {row["operation_type"] for row in lineage.json()["data"]}
    assert {"ingest", "reindex", "archive", "delete"} <= ops


def test_vector_failure_becomes_partially_indexed(monkeypatch):
    client = _auth_client(monkeypatch)
    monkeypatch.setattr(
        embedding_manager,
        "rebuild_vectors",
        lambda dataset_uuid, chunks, metadata: {
            "status": "failed",
            "collection_name": "kuro_ingestion_pantronux",
            "vector_ids": [],
            "embedding_count": 0,
            "memory_scope": "chroma_only",
            "error": "vector down",
        },
    )
    dataset = _upload_dataset(client, "beta.md", b"# Header\n\nChunk body")
    assert dataset["ingestion_status"] == "partially_indexed"
