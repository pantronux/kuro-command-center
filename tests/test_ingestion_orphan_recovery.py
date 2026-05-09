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
from kuro_backend.config import settings
from kuro_backend.ingestion_center import ingestion_manager


def _auth_client(monkeypatch, username="Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    monkeypatch.setattr(
        ingestion_manager,
        "schedule_ingestion_job",
        lambda background_tasks, job_id: ingestion_manager.process_ingestion_job(job_id),
    )
    return TestClient(main.app)


def test_orphan_source_scan_and_reingest(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WORKING_DIR", str(tmp_path))
    source_dir = tmp_path / "uploaded_files" / "Pantronux" / "ingestion_center"
    source_dir.mkdir(parents=True, exist_ok=True)
    orphan_path = source_dir / "recovered_notes.md"
    orphan_path.write_text("# Recovery\n\nThis file should be re-ingested.", encoding="utf-8")

    client = _auth_client(monkeypatch)

    response = client.get("/api/ingestion/orphan-sources", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["orphan_count"] >= 1
    assert any(item["filename"] == "recovered_notes.md" for item in payload["files"])

    response = client.post(
        "/api/ingestion/orphan-sources/reingest",
        json={"filenames": ["recovered_notes.md"]},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert response.status_code == 202
    assert response.json()["data"]["recovered_count"] == 1

    response = client.get("/api/ingestion/orphan-sources", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert response.status_code == 200
    assert all(item["filename"] != "recovered_notes.md" for item in response.json()["data"]["files"])
