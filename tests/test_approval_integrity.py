"""Approval / HITL integrity tests.

Purpose: Ensure advanced_execution_tool approval/reject payloads do not mutate SSoT out-of-band.
Covers: tools.base_tools.advanced_execution_tool, openclaw bridge stubs.
Fixtures: monkeypatched openclaw_bridge + temp core_service DBs.
"""
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
    def _launch_app(*args, **kwargs):
        return _FakePhoenixApp()
    fake_phoenix.launch_app = _launch_app
    sys.modules["phoenix"] = fake_phoenix

from kuro_backend import langgraph_core


def test_nonce_mismatch_keeps_pending(monkeypatch):
    scope = "test_scope_nonce_mismatch"
    langgraph_core._clear_pending_approval(scope)
    nonce = langgraph_core._set_pending_approval(
        scope,
        "manage_files",
        {"action": "delete", "filename": "x.txt"},
        "dangerous action",
        trace_id="trace-test",
    )
    assert nonce

    monkeypatch.setattr(langgraph_core, "_execute_tool", lambda *args, **kwargs: {"status": "success"})
    response = langgraph_core._maybe_handle_pending_approval("approve wrongnonce", scope)
    assert "HITL APPROVAL REQUIRED" in response
    assert langgraph_core._get_pending_approval(scope) is not None

    langgraph_core._clear_pending_approval(scope)


def test_cancel_clears_pending():
    scope = "test_scope_cancel"
    langgraph_core._clear_pending_approval(scope)
    langgraph_core._set_pending_approval(
        scope,
        "generate_report_template",
        {"template_type": "audit_findings"},
        "needs approval",
        trace_id="trace-cancel",
    )
    response = langgraph_core._maybe_handle_pending_approval("cancel", scope)
    assert response == "Approval dibatalkan. Tool tidak dieksekusi."
    assert langgraph_core._get_pending_approval(scope) is None
