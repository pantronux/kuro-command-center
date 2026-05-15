"""Observability V2 tests for Prompt 7."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

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


def _auth_client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_trace_middleware_adds_header(monkeypatch):
    client = _auth_client(monkeypatch)
    resp = client.get("/api/runtimes", cookies={main.COOKIE_NAME: "Bearer dummy"})
    assert "X-Trace-ID" in resp.headers
    assert resp.headers["X-Trace-ID"].startswith("trace_")


def test_trace_id_preserved_from_request_header(monkeypatch):
    client = _auth_client(monkeypatch)
    resp = client.get(
        "/api/runtimes",
        headers={"X-Trace-ID": "trace_custom_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.headers["X-Trace-ID"] == "trace_custom_001"


def test_cognition_trace_finish_persists_to_db():
    from kuro_backend.telemetry.cognition_trace import CognitionTrace

    trace = CognitionTrace(
        trace_id="trace_test",
        runtime_id="sovereign",
        username="testuser",
        chat_id="chat_001",
    )
    trace.record_node("supervisor_node")
    trace.record_memory_access("kuro.sovereign")
    with patch("kuro_backend.telemetry.cognition_trace.intelligence_db") as mock_db:
        trace.finish()
        mock_db.log_cognition_trace.assert_called_once()


def test_cognition_trace_failure_does_not_crash():
    from kuro_backend.telemetry.cognition_trace import CognitionTrace

    trace = CognitionTrace(
        trace_id="t",
        runtime_id="qa",
        username="u",
        chat_id="c",
    )
    with patch(
        "kuro_backend.telemetry.cognition_trace.intelligence_db.log_cognition_trace",
        side_effect=Exception("DB down"),
    ):
        trace.finish()  # must not raise


def test_runtime_health_returns_200_for_admin(monkeypatch):
    client = _auth_client(monkeypatch, username="Pantronux")
    resp = client.get(
        "/api/admin/runtime-health",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_runtime_health_returns_403_for_non_admin(monkeypatch):
    client = _auth_client(monkeypatch, username="Faikhira")
    resp = client.get(
        "/api/admin/runtime-health",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 403


def test_vocab_sanitizer_replaces_jargon():
    from kuro_backend.vocabulary.sanitizer import sanitize_response

    result = sanitize_response("Mem0 updated the episodic buffer successfully.")
    assert "Mem0" not in result
    assert "episodic buffer" not in result.lower()


def test_vocab_sanitizer_bypassed_in_dev_mode(monkeypatch):
    monkeypatch.setenv("KURO_DEV_MODE", "true")
    from importlib import reload
    from kuro_backend.vocabulary import sanitizer

    reload(sanitizer)
    result = sanitizer.sanitize_response("Mem0 and ChromaDB are running.")
    assert "Mem0" in result
