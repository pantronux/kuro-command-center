import os
import sys
import types
from pathlib import Path

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

from kuro_backend.ingestion_center import ingestion_registry


def test_ingestion_schema_creates_tables_and_indexes():
    ingestion_registry.init_db()
    tables = ingestion_registry.fetch_all("SELECT name FROM sqlite_master WHERE type = 'table'")
    table_names = {row["name"] for row in tables}
    assert {"ingested_datasets", "dataset_chunks", "ingestion_jobs", "retrieval_analytics", "dataset_lineage"} <= table_names

    indexes = ingestion_registry.fetch_all("SELECT name FROM sqlite_master WHERE type = 'index'")
    index_names = {row["name"] for row in indexes}
    assert "idx_ingested_dataset_uuid" in index_names
    assert "idx_dataset_lineage_dataset_created" in index_names
