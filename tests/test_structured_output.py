"""Structured output engine tests for Prompt 4."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import types
from pathlib import Path
from typing import List, Tuple
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


def _parse_sse_events(payload: str) -> List[Tuple[str, str]]:
    events: List[Tuple[str, str]] = []
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
        if data_lines:
            events.append((event_type, "\n".join(data_lines).strip()))
    return events


def _auth_client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_validate_output_valid_qa():
    from kuro_backend.output.output_validator import validate_output

    payload = {
        "task_type": "testcase_generation",
        "test_cases": [],
        "schema_version": "qa_output_v1",
    }
    ok, model, err = validate_output(json.dumps(payload), "qa_output_v1")
    assert ok is True
    assert model is not None
    assert err is None


def test_validate_output_invalid_json():
    from kuro_backend.output.output_validator import validate_output

    ok, model, err = validate_output("not json at all", "qa_output_v1")
    assert ok is False
    assert model is None
    assert err is not None


def test_validate_output_strips_markdown_fences():
    from kuro_backend.output.output_validator import validate_output

    payload = '```json\n{"task_type":"testcase_generation","test_cases":[]}\n```'
    ok, model, err = validate_output(payload, "qa_output_v1")
    assert ok is True
    assert err is None
    assert model is not None


def test_attempt_repair_returns_safe_on_llm_unavailable():
    from kuro_backend.output.output_repair import attempt_repair

    with patch(
        "kuro_backend.output.output_repair._call_repair_llm",
        return_value=None,
    ):
        ok, model, err = asyncio.run(
            attempt_repair("bad json", "qa_output_v1", "parse error")
        )
    assert ok is False
    assert model is None
    assert err is not None


def test_sovereign_runtime_skips_validation():
    from kuro_backend.runtime.runtime_registry import RuntimeRegistry

    config = RuntimeRegistry.get("sovereign")
    assert config.structured_output_contract is None


def test_sse_structured_output_event_format(monkeypatch):
    async def _fake_stream(*args, **kwargs):
        metrics = kwargs.get("stream_metrics")
        if isinstance(metrics, dict):
            metrics["structured_output"] = {
                "task_type": "testcase_generation",
                "test_cases": [],
                "schema_version": "qa_output_v1",
            }
            metrics["output_schema_valid"] = True
        yield "structured output ready"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)
    resp = client.post(
        "/api/chat/stream?runtime_id=qa",
        data={
            "message": "buat testcase",
            "persona": "consultant",
            "chat_id": "qa_structured_stream_001",
        },
        headers={"X-Chat-Session": "qa_structured_stream_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    names = [event for event, _ in events]
    assert "structured_output" in names
    assert "complete" in names
    assert names.index("structured_output") < names.index("complete")
