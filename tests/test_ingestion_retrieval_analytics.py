from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WORKING_DIR", str(PROJECT_ROOT))
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

from kuro_backend import memory_coordinator
from kuro_backend.ingestion_center import ingestion_registry


@pytest.fixture()
def isolated_ingestion_db(monkeypatch, tmp_path):
    db_path = tmp_path / "kuro_ingestion_retrieval_test.db"
    monkeypatch.setattr(ingestion_registry, "DB_PATH", str(db_path))
    ingestion_registry._reset_schema_ready_for_tests()
    ingestion_registry.init_db()
    return ingestion_registry


def test_bridge_logs_retrieval_events_and_increments_chunk_counter(monkeypatch, isolated_ingestion_db):
    registry = isolated_ingestion_db

    registry.create_dataset(
        {
            "dataset_uuid": "ds_analytics_1",
            "dataset_name": "ISO 27005",
            "owner_username": "alice",
            "ingestion_status": "completed",
            "source_type": "txt",
            "category": "policy",
            "tags": [],
            "metadata": {},
        }
    )
    registry.replace_chunks(
        "ds_analytics_1",
        [
            {
                "chunk_index": 2,
                "chunk_text": "Risk criteria and treatment option mapping.",
                "chunk_hash": "ds_analytics_1-2",
                "token_count": 7,
                "metadata": {},
            }
        ],
    )

    from kuro_backend.ingestion_center import embedding_manager

    monkeypatch.setattr(
        embedding_manager,
        "query_owner_collection",
        lambda owner_username, query_text, top_k=5: {
            "status": "success",
            "ids": ["ds_analytics_1:2"],
            "documents": ["Risk criteria and treatment option mapping."],
            "metadatas": [{"dataset_uuid": "ds_analytics_1", "chunk_index": 2, "dataset_name": "ISO 27005"}],
            "distances": [0.1],
        },
    )

    evidence = memory_coordinator._retrieve_ingestion_evidence(
        "risk criteria",
        username="alice",
        chat_id="chat-analytics",
        top_k=5,
        max_chars=2500,
        min_score=0.0,
    )

    assert len(evidence) == 1

    events = registry.list_retrieval_events(limit=10)
    assert len(events) == 1
    assert events[0]["dataset_uuid"] == "ds_analytics_1"
    assert events[0]["retrieval_source"] == "chat_bridge"

    chunk_row = registry.get_chunk_by_dataset_and_index("ds_analytics_1", 2)
    assert int(chunk_row.get("retrieval_count") or 0) == 1
