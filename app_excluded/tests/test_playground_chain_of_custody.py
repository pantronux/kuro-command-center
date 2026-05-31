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


def test_chain_of_custody_actor_and_order(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "kuro_playground.db"))
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("KURO_PLAYGROUND_HALLUCINATION_ANALYZER", "false")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())
    monkeypatch.setattr(service.router, "invoke_single", lambda provider_id, req: _response(provider_id, "result"))

    sid = service.create_session(mode="research", actor="Pantronux")["session_id"]
    service.execute_single(session_id=sid, provider_id="openai", prompt="hello", actor="Pantronux")

    custody = service.db.list_chain_of_custody()
    actions = [row["action_type"] for row in custody]
    assert any(a == "SESSION_CREATED" for a in actions)
    assert any(a == "EXECUTION_CREATED" for a in actions)
    assert all(row["actor"] == "Pantronux" for row in custody if row["action_type"] in {"SESSION_CREATED", "EXECUTION_CREATED", "RAW_PERSISTED", "CANONICAL_CREATED"})
