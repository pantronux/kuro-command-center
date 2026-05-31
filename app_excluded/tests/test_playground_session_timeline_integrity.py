from __future__ import annotations

import importlib
from datetime import datetime, timezone

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


def test_session_timeline_hash_stable_and_drifts_on_change(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "kuro_playground.db"))
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())
    monkeypatch.setattr(service.router, "invoke_single", lambda provider_id, req: _response(provider_id, req.prompt))

    sid = service.create_session(mode="research", actor="Pantronux")["session_id"]
    service.execute_single(session_id=sid, provider_id="openai", prompt="hello", actor="Pantronux")

    before_rows = service.db.list_chain_of_custody(artifact_id=sid)
    before_count = len([r for r in before_rows if r.get("action_type") == "SESSION_TIMELINE_HASHED"])

    t1 = service.build_session_timeline_integrity(session_id=sid, actor="Pantronux")
    t2 = service.build_session_timeline_integrity(session_id=sid, actor="Pantronux")
    assert t1["session_integrity_hash"] == t2["session_integrity_hash"]

    after_rows = service.db.list_chain_of_custody(artifact_id=sid)
    after_count = len([r for r in after_rows if r.get("action_type") == "SESSION_TIMELINE_HASHED"])
    assert after_count == before_count

    service.execute_single(session_id=sid, provider_id="openai", prompt="hello-2", actor="Pantronux")
    t3 = service.build_session_timeline_integrity(session_id=sid, actor="Pantronux")
    assert t3["session_integrity_hash"] != t1["session_integrity_hash"]

    history = service.get_session_history(session_id=sid)
    assert "session_timeline_integrity" in history
    assert history["session_timeline_integrity"]["session_id"] == sid
