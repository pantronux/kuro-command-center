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
    db_path = tmp_path / "kuro_ingestion_bridge_test.db"
    monkeypatch.setattr(ingestion_registry, "DB_PATH", str(db_path))
    ingestion_registry._reset_schema_ready_for_tests()
    ingestion_registry.init_db()
    return ingestion_registry


def _create_dataset(registry, *, dataset_uuid: str, name: str, owner: str, status: str, archived: bool = False, deleted: bool = False):
    payload = {
        "dataset_uuid": dataset_uuid,
        "dataset_name": name,
        "owner_username": owner,
        "ingestion_status": status,
        "source_type": "txt",
        "category": "policy",
        "tags": [],
        "metadata": {},
        "archived_at": registry.now_iso() if archived else None,
        "deleted_at": registry.now_iso() if deleted else None,
    }
    registry.create_dataset(payload)


def _create_chunk(registry, dataset_uuid: str, chunk_index: int, text: str):
    registry.replace_chunks(
        dataset_uuid,
        [
            {
                "chunk_index": chunk_index,
                "chunk_text": text,
                "chunk_hash": f"{dataset_uuid}-{chunk_index}",
                "token_count": max(1, len(text.split())),
                "metadata": {},
            }
        ],
    )


def test_retrieve_ingestion_evidence_filters_owner_status_and_budget(monkeypatch, isolated_ingestion_db):
    registry = isolated_ingestion_db

    _create_dataset(registry, dataset_uuid="ds_ok_1", name="ISO 27005", owner="alice", status="completed")
    _create_dataset(registry, dataset_uuid="ds_ok_2", name="NIST RMF", owner="alice", status="partially_indexed")
    _create_dataset(registry, dataset_uuid="ds_failed", name="Failed", owner="alice", status="failed")
    _create_dataset(registry, dataset_uuid="ds_other_user", name="Other User", owner="bob", status="completed")
    _create_dataset(registry, dataset_uuid="ds_archived", name="Archived", owner="alice", status="archived", archived=True)
    _create_dataset(registry, dataset_uuid="ds_deleted", name="Deleted", owner="alice", status="deleted", deleted=True)

    _create_chunk(registry, "ds_ok_1", 2, "Alpha policy guidance for risk treatment and governance continuity.")
    _create_chunk(registry, "ds_ok_2", 5, "Beta control mapping and implementation details for evidence workflow.")
    _create_chunk(registry, "ds_failed", 1, "Should never be selected.")
    _create_chunk(registry, "ds_other_user", 1, "Should never leak across users.")
    _create_chunk(registry, "ds_archived", 1, "Archived source should be excluded.")
    _create_chunk(registry, "ds_deleted", 1, "Deleted source should be excluded.")

    from kuro_backend.ingestion_center import embedding_manager

    monkeypatch.setattr(
        embedding_manager,
        "query_owner_collection",
        lambda owner_username, query_text, top_k=5: {
            "status": "success",
            "ids": [
                "ds_ok_2:5",
                "ds_ok_1:2",
                "ds_failed:1",
                "ds_other_user:1",
                "ds_archived:1",
                "ds_deleted:1",
            ],
            "documents": [
                "beta",
                "alpha",
                "failed",
                "other",
                "archived",
                "deleted",
            ],
            "metadatas": [
                {"dataset_uuid": "ds_ok_2", "chunk_index": 5, "dataset_name": "NIST RMF"},
                {"dataset_uuid": "ds_ok_1", "chunk_index": 2, "dataset_name": "ISO 27005"},
                {"dataset_uuid": "ds_failed", "chunk_index": 1, "dataset_name": "Failed"},
                {"dataset_uuid": "ds_other_user", "chunk_index": 1, "dataset_name": "Other User"},
                {"dataset_uuid": "ds_archived", "chunk_index": 1, "dataset_name": "Archived"},
                {"dataset_uuid": "ds_deleted", "chunk_index": 1, "dataset_name": "Deleted"},
            ],
            "distances": [0.1, 0.2, 0.01, 0.01, 0.01, 0.01],
        },
    )

    evidence = memory_coordinator._retrieve_ingestion_evidence(
        "risk treatment",
        username="alice",
        chat_id="chat-1",
        top_k=5,
        max_chars=120,
        min_score=0.0,
    )

    assert evidence
    assert [row["dataset_uuid"] for row in evidence] == ["ds_ok_2", "ds_ok_1"]
    assert all(row["dataset_name"] in {"NIST RMF", "ISO 27005"} for row in evidence)
    assert len(evidence) <= 5
    assert sum(len(str(row.get("chunk_text") or "")) for row in evidence) <= 120


def test_retrieve_ingestion_evidence_silent_fallback_on_query_error(monkeypatch, isolated_ingestion_db):
    from kuro_backend.ingestion_center import embedding_manager

    monkeypatch.setattr(
        embedding_manager,
        "query_owner_collection",
        lambda owner_username, query_text, top_k=5: (_ for _ in ()).throw(RuntimeError("query failed")),
    )

    evidence = memory_coordinator._retrieve_ingestion_evidence(
        "anything",
        username="alice",
        chat_id="chat-2",
        top_k=5,
        max_chars=2500,
        min_score=0.0,
    )
    assert evidence == []


def test_build_context_for_llm_includes_ingestion_block(monkeypatch):
    monkeypatch.setattr("kuro_backend.memory_manager.get_short_term", lambda **kwargs: [])
    monkeypatch.setattr("kuro_backend.memory_manager.get_session_files", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        memory_coordinator,
        "_retrieve_ingestion_evidence",
        lambda *args, **kwargs: [
            {
                "dataset_uuid": "ds_ok_1",
                "dataset_name": "ISO 27005",
                "chunk_index": 2,
                "chunk_id": 10,
                "score": 0.93,
                "chunk_text": "Ringkasan risiko operasional.",
            }
        ],
    )

    ctx = memory_coordinator.build_context_for_llm(
        "jelaskan risk treatment",
        "consultant",
        include_referent_grounding=False,
        username="alice",
        chat_id="chat-3",
    )

    assert ctx.get("ingestion_sources")
    assert "[INGESTION_KNOWLEDGE_CONTEXT]" in (ctx.get("ingestion_context_block") or "")
    assert "bagian" in (ctx.get("ingestion_context_block") or "")
