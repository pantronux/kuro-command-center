"""SSE/chat API contract tests.

Purpose: Lock the /api/chat SSE frame schema and termination semantics.
Covers: main.py SSE helpers and frame serialization.
Fixtures: monkeypatch on LangGraph core, fake Gemini streams.
"""
import json
import sys
import types
from pathlib import Path
from typing import List, Tuple

from fastapi.testclient import TestClient

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

import main


def _parse_sse_events(payload: str) -> List[Tuple[str, dict]]:
    events: List[Tuple[str, dict]] = []
    normalized = payload.replace("\r\n", "\n")
    for block in normalized.split("\n\n"):
        if not block.strip():
            continue
        event_type = "message"
        data_lines = []
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                data_lines.append(line[6:])
        if not data_lines:
            continue
        data_str = "\n".join(data_lines).strip()
        if data_str == "[DONE]":
            data = {"status": "done"}
        else:
            try:
                data = json.loads(data_str)
            except Exception:
                data = {"text": data_str}
        events.append((event_type, data))
    return events


def _auth_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": "tester"})
    return TestClient(main.app)


def test_stream_contract_event_order(monkeypatch):
    async def _fake_stream(*args, **kwargs):
        yield "halo "
        yield "dunia"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)
    response = client.post(
        "/api/chat/stream",
        data={"message": "tes", "persona": "consultant"},
        headers={"X-Chat-Session": "session_test_12345"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert events[0][0] == "meta"
    chunk_events = [evt for evt in events if evt[0] == "chunk"]
    assert len(chunk_events) >= 1
    # Check the complete event, which is the second to last event since we added [DONE]
    comp_evt = [evt for evt in events if evt[0] == "complete"][0]
    assert comp_evt[1].get("meta", {}).get("ttfb_ms") is not None
    assert "trace_id" in comp_evt[1]


def test_stream_contract_error_event(monkeypatch):
    async def _fake_stream(*args, **kwargs):
        raise RuntimeError("stream boom")
        yield  # pragma: no cover

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)
    response = client.post(
        "/api/chat/stream",
        data={"message": "tes", "persona": "consultant"},
        headers={"X-Chat-Session": "session_test_12345"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert events[0][0] == "meta"
    err_evt = [evt for evt in events if evt[0] == "error"][0]
    assert err_evt[1]["status"] == "error"
    assert "stream boom" in err_evt[1]["error"]


def test_stream_contract_includes_auditor_export_suggestion(monkeypatch):
    async def _fake_stream(*args, **kwargs):
        yield "| Test Case | Steps | Expected Result |\n"
        yield "| TC-01 | Open page | Page loads |\n"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)
    response = client.post(
        "/api/chat/stream",
        data={"message": "buat test case", "persona": "auditor"},
        headers={"X-Chat-Session": "session_test_12345"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    comp_evt = [evt for evt in events if evt[0] == "complete"][0]
    suggestion = comp_evt[1].get("meta", {}).get("export_suggestion")
    assert suggestion is not None
    assert suggestion["format"] == "xlsx"
    assert suggestion["target"] == "selected_messages"
    assert len(suggestion["message_ids"]) == 1


def test_stream_contract_includes_advisor_export_suggestions(monkeypatch):
    async def _fake_stream(*args, **kwargs):
        yield "## Executive Summary\n"
        yield "| Metric | Value |\n|---|---|\n| Risk | Medium |\n"
        yield "Recommendation: proceed with mitigation roadmap.\n"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)
    response = client.post(
        "/api/chat/stream",
        data={"message": "buat report", "persona": "advisor"},
        headers={"X-Chat-Session": "session_test_22345"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    comp_evt = [evt for evt in events if evt[0] == "complete"][0]
    suggestions = comp_evt[1].get("meta", {}).get("export_suggestions") or []
    formats = {item["format"] for item in suggestions}
    assert {"pdf", "docx", "xlsx"}.issubset(formats)


def test_stream_contract_includes_chancellor_export_suggestions(monkeypatch):
    async def _fake_stream(*args, **kwargs):
        yield "| Category | Amount |\n|---|---|\n| Hosting | 20 |\n"
        yield "Financial table prepared.\n"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)
    response = client.post(
        "/api/chat/stream",
        data={"message": "buat tabel budget", "persona": "chancellor"},
        headers={"X-Chat-Session": "session_test_32345"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    comp_evt = [evt for evt in events if evt[0] == "complete"][0]
    suggestions = comp_evt[1].get("meta", {}).get("export_suggestions") or []
    formats = {item["format"] for item in suggestions}
    assert {"xlsx", "csv"}.issubset(formats)


def test_stream_persists_export_suggestions_in_history(monkeypatch):
    async def _fake_stream(*args, **kwargs):
        yield "| Test Case | Steps | Expected Result |\n"
        yield "| TC-01 | Open page | Page loads |\n"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)
    response = client.post(
        "/api/chat/stream",
        data={
            "message": "buat test case",
            "persona": "auditor",
            "chat_id": "auditor_hist_1",
        },
        headers={"X-Chat-Session": "auditor_hist_1"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert response.status_code == 200

    history_response = client.get(
        "/api/history?platform=web&persona=auditor&chat_id=auditor_hist_1",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert history_response.status_code == 200
    payload = history_response.json()
    assistant_rows = [row for row in payload["history"] if row["role"] == "assistant"]
    assert assistant_rows
    assert assistant_rows[-1]["export_suggestions"]
    assert assistant_rows[-1]["export_suggestions"][0]["format"] == "xlsx"


def test_system_status_includes_backup_block(monkeypatch):
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": "Pantronux"})
    monkeypatch.setattr(main.tools, "get_system_status", lambda: "health-ok")
    monkeypatch.setattr(
        main,
        "_build_system_status_backup_payload",
        lambda: {
            "last_backup_at": "2026-05-08 01:00:12",
            "last_backup_status": "success",
            "last_backup_type": "nightly",
            "files_backed_up": 9,
            "total_size_mb": 47.3,
            "duration_seconds": 12.4,
            "retain_days": 30,
            "backup_dir_size_mb": 312.5,
            "backup_count_daily": 7,
            "backup_count_pre_migration": 3,
            "assets_covered": ["kuro_chat_history.db"],
            "next_backup_at": "2026-05-09 01:00:00",
            "error_message": None,
        },
    )
    client = TestClient(main.app)

    response = client.get(
        "/api/system-status",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["system_health_report"] == "health-ok"
    assert payload["data"]["backup"]["last_backup_status"] == "success"
