from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone

import pytest

from playground_runtime.errors import PlaygroundError
from playground_runtime.providers.adapters.base_adapter import ProviderResponse
from playground_runtime.service import PlaygroundRuntimeService


def _reload_config_module():
    import playground_runtime.config as config_module

    importlib.reload(config_module)
    config_module.get_settings.cache_clear()
    return config_module


def _response(provider_id: str, text: str) -> ProviderResponse:
    return ProviderResponse(
        provider_id=provider_id,
        model_id=f"{provider_id}-model",
        model_version=f"{provider_id}-model-v1",
        request_id=f"req-{provider_id}",
        raw_json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": {"total_tokens": 10}},
        response_text=text,
        finish_reason="stop",
        input_tokens=5,
        output_tokens=5,
        total_tokens=10,
        latency_ms=12.0,
        collected_at_utc=datetime.now(timezone.utc),
    )


def test_playground_session_history_and_custom_upsert(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "kuro_playground.db"))
    monkeypatch.setenv("KURO_PLAYGROUND_HALLUCINATION_ANALYZER", "false")
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy-openai")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())

    created = service.create_session(mode="research")
    assert created["reconnected"] is False
    sid_default = created["session_id"]

    custom_new = service.create_session(mode="forensic", session_id="lab-session-01")
    assert custom_new["session_id"] == "lab-session-01"
    assert custom_new["reconnected"] is False

    custom_existing = service.create_session(mode="forensic", session_id="lab-session-01")
    assert custom_existing["session_id"] == "lab-session-01"
    assert custom_existing["reconnected"] is True

    monkeypatch.setattr(service.router, "invoke_single", lambda provider_id, req: _response(provider_id, "single result"))
    trace = service.execute_single(
        session_id=sid_default,
        provider_id="openai",
        prompt="hello",
    )
    execution_id = trace["execution_id"]

    sessions = service.list_sessions(limit=20)
    assert len(sessions) >= 2
    assert sessions[0]["created_at_utc"] >= sessions[-1]["created_at_utc"]

    latest = service.get_latest_session()
    assert latest is not None
    assert "session_id" in latest

    history = service.get_session_history(sid_default)
    assert history["session"]["session_id"] == sid_default
    assert isinstance(history["executions"], list)
    assert "traces_summary" in history

    session_filename, session_body = service.build_session_json_artifact(sid_default, "session")
    assert session_filename.startswith("playground-session-")
    assert json.loads(session_body)["session"]["session_id"] == sid_default

    raw_filename, raw_body = service.build_session_json_artifact(
        sid_default,
        "execution_raw",
        execution_id=execution_id,
    )
    assert raw_filename.startswith("playground-exec-raw-")
    assert json.loads(raw_body)["execution"]["id"] == execution_id

    trace_filename, trace_body = service.build_session_json_artifact(
        sid_default,
        "execution_trace",
        execution_id=execution_id,
    )
    assert trace_filename.startswith("playground-exec-trace-")
    assert json.loads(trace_body)["execution"]["id"] == execution_id


def test_playground_session_history_error_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "kuro_playground.db"))
    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())

    with pytest.raises(PlaygroundError):
        service.create_session(mode="research", session_id="bad id with spaces")

    with pytest.raises(PlaygroundError):
        service.build_session_json_artifact("missing-session", "session")

    session = service.create_session(mode="research")
    sid = session["session_id"]

    with pytest.raises(PlaygroundError):
        service.build_session_json_artifact(sid, "execution_raw")

    with pytest.raises(PlaygroundError):
        service.build_session_json_artifact(sid, "execution_raw", execution_id="missing-exec")
