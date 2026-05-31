from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import pytest

from playground_runtime.db.playground_db import PlaygroundDB
from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace
from playground_runtime.schema.evidence_artifact import EvidenceArtifact


def test_playground_db_bootstrap_and_raw_evidence_immutable(tmp_path):
    db_path = tmp_path / "kuro_playground.db"
    db = PlaygroundDB(str(db_path))
    db.init_db()

    session_id = db.create_session(mode="research", runtime_config_hash="hash-1")
    execution_id = db.insert_model_execution(
        session_id=session_id,
        provider_id="openai",
        model_id="gpt-test",
        model_version="gpt-test-v1",
        request_id="req-1",
        prompt_sha256=sha256(b"hello").hexdigest(),
        dataset_version=None,
        latency_ms=1.0,
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        finish_reason="stop",
    )

    artifact = EvidenceArtifact(
        provider_id="openai",
        model_version="gpt-test-v1",
        response_schema_version="provider_raw/1.0",
        request_id="req-1",
        prompt_sha256=sha256(b"hello").hexdigest(),
        dataset_version=None,
        collected_at_utc=datetime.now(timezone.utc),
        raw_json={"id": "abc", "choices": []},
    )
    raw_id = db.insert_raw_evidence(session_id=session_id, execution_id=execution_id, artifact=artifact)

    trace = CanonicalInferenceTrace(
        trace_id=str(uuid4()),
        session_id=session_id,
        execution_id=execution_id,
        provider_id="openai",
        model_id="gpt-test",
        model_version="gpt-test-v1",
        schema_version="openai/1.0.0",
        prompt_sha256=sha256(b"hello").hexdigest(),
        dataset_version=None,
        collected_at_utc=datetime.now(timezone.utc),
        response_text="hello world",
        finish_reason="stop",
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        latency_ms=1.0,
        grounding_chunks=[],
        citation_objects=[],
        safety_ratings=None,
        provider_raw_id=raw_id,
        forensic_flags=[],
        normalization_warnings=[],
        extra_fields={},
    )
    db.insert_canonical_trace(trace)

    conn = sqlite3.connect(str(db_path))
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE raw_evidence SET raw_json='{}' WHERE id=?", (raw_id,))
        conn.commit()
    conn.close()

    assert db.purge_expired_evidence(retention_days=90) == 0
