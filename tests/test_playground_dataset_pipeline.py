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
        request_id=f"req-{provider_id}-{text}",
        raw_json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": {"total_tokens": 10}},
        response_text=text,
        finish_reason="stop",
        input_tokens=5,
        output_tokens=5,
        total_tokens=10,
        latency_ms=12.0,
        collected_at_utc=datetime.now(timezone.utc),
    )


def test_execute_dataset_sync_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "kuro_playground.db"))
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("KURO_PLAYGROUND_HALLUCINATION_ANALYZER", "false")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())
    monkeypatch.setattr(service.router, "invoke_single", lambda provider_id, req: _response(provider_id, req.prompt))

    sid = service.create_session(mode="research", actor="Pantronux")["session_id"]
    result = service.execute_dataset(
        session_id=sid,
        provider_ids=["openai"],
        mode="research",
        dataset_items=[
            {"prompt": "p1", "dataset_version": "d1", "metadata": {}},
            {"prompt": "p2", "dataset_version": "d1", "metadata": {}},
        ],
        execution_config={"temperature": 0.2},
        actor="Pantronux",
    )

    assert result["summary"]["completed_count"] == 2
    rec = service.db.get_dataset_execution(result["summary"]["dataset_execution_id"])
    assert rec is not None
    assert rec["status"] == "completed"
