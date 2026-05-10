"""Boundary guard tests for V2 Prompt 2."""

from __future__ import annotations

import os
import sys
import types
from importlib import reload
from pathlib import Path
from unittest.mock import patch

import pytest
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


def make_ctx(runtime_id: str = "qa"):
    from kuro_backend.runtime.runtime_context import resolve_runtime_context

    return resolve_runtime_context(
        runtime_id,
        username="testuser",
        trace_id="trace_test_001",
    )


def test_qa_cannot_access_governance_memory_strict(monkeypatch):
    monkeypatch.setenv("KURO_V2_STRICT_MODE", "true")
    from kuro_backend.runtime import boundary_guard

    reload(boundary_guard)
    with patch.object(boundary_guard, "_record_violation"):
        with pytest.raises(boundary_guard.BoundaryViolationError):
            boundary_guard.assert_memory_access(make_ctx("qa"), "kuro.governance")


def test_audit_mode_logs_but_does_not_block(monkeypatch):
    monkeypatch.setenv("KURO_V2_STRICT_MODE", "false")
    from kuro_backend.runtime import boundary_guard

    reload(boundary_guard)
    with patch.object(boundary_guard, "_record_violation") as mock_record:
        boundary_guard.assert_memory_access(make_ctx("qa"), "kuro.governance")
        mock_record.assert_called_once()


def test_violation_includes_trace_id(monkeypatch):
    monkeypatch.setenv("KURO_V2_STRICT_MODE", "false")
    from kuro_backend.runtime import boundary_guard

    reload(boundary_guard)
    ctx = make_ctx("qa")
    with patch.object(boundary_guard, "_record_violation") as mock_record:
        boundary_guard.assert_memory_access(ctx, "kuro.governance")
    assert mock_record.call_count == 1
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs.get("trace_id") == "trace_test_001"


def test_shared_namespace_accessible_by_all(monkeypatch):
    monkeypatch.setenv("KURO_V2_STRICT_MODE", "true")
    from kuro_backend.runtime import boundary_guard

    reload(boundary_guard)
    for runtime_id in ["sovereign", "qa", "research"]:
        ctx = make_ctx(runtime_id)
        boundary_guard.assert_memory_access(ctx, "kuro.shared")


def test_own_namespace_always_allowed(monkeypatch):
    monkeypatch.setenv("KURO_V2_STRICT_MODE", "true")
    from kuro_backend.runtime import boundary_guard

    reload(boundary_guard)
    ctx = make_ctx("qa")
    boundary_guard.assert_memory_access(ctx, "kuro.qa")


def test_tool_not_in_registry_blocked_strict(monkeypatch):
    monkeypatch.setenv("KURO_V2_STRICT_MODE", "true")
    from kuro_backend.runtime import boundary_guard

    reload(boundary_guard)
    with patch.object(boundary_guard, "_record_violation"):
        with pytest.raises(boundary_guard.BoundaryViolationError):
            boundary_guard.assert_tool_access(make_ctx("qa"), "market_analysis")


def test_e2e_strict_mode_safe_failure(monkeypatch):
    monkeypatch.setenv("KURO_V2_STRICT_MODE", "true")
    from kuro_backend.runtime import boundary_guard

    async def _boundary_fail_stream(*args, **kwargs):
        raise boundary_guard.BoundaryViolationError("tool blocked by boundary")
        yield  # pragma: no cover

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _boundary_fail_stream)
    client = _auth_client(monkeypatch)
    resp = client.post(
        "/api/chat/stream?runtime_id=qa",
        data={"message": "run market analysis", "persona": "consultant"},
        headers={"X-Chat-Session": "session_boundary_qa_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "tool blocked by boundary" in resp.text


def test_legacy_chat_unaffected_by_boundary_guard(monkeypatch):
    monkeypatch.setenv("KURO_V2_STRICT_MODE", "false")

    async def _ok_stream(*args, **kwargs):
        yield "legacy ok"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _ok_stream)
    client = _auth_client(monkeypatch)
    resp = client.post(
        "/api/chat/stream",
        data={"message": "halo", "persona": "consultant"},
        headers={"X-Chat-Session": "session_legacy_qa_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 200
    assert "event: complete" in resp.text


def test_boundary_violations_admin_route_403_non_admin(monkeypatch):
    client = _auth_client(monkeypatch, username="Faikhira")
    resp = client.get(
        "/api/admin/boundary-violations",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 403
