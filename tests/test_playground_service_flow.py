from __future__ import annotations

import importlib
import sqlite3
from datetime import datetime, timezone

from playground_runtime.providers.adapters.base_adapter import ProviderResponse
from playground_runtime.providers.router import ComparativeResult
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


def test_playground_service_single_and_comparative_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "kuro_playground.db"))
    monkeypatch.setenv("KURO_PLAYGROUND_HALLUCINATION_ANALYZER", "false")
    monkeypatch.setenv("KURO_PLAYGROUND_EPISTEMIC_DIFF", "true")
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy-openai")
    monkeypatch.setenv("PLAYGROUND_GEMINI_API_KEY", "dummy-gemini")

    cfg = _reload_config_module()
    settings = cfg.PlaygroundSettings()
    service = PlaygroundRuntimeService(settings=settings)

    session = service.create_session(mode="comparative")
    session_id = session["session_id"]

    monkeypatch.setattr(service.router, "invoke_single", lambda provider_id, req: _response(provider_id, "single result"))
    single = service.execute_single(
        session_id=session_id,
        provider_id="openai",
        prompt="hello",
        dataset_version="d1",
    )
    assert single["provider_id"] == "openai"
    assert len(service.db.list_raw_evidence(session_id)) == 1
    assert len(service.db.list_canonical_traces(session_id)) == 1

    def _fake_comparative(provider_ids, req):
        return ComparativeResult(
            prompt_sha256="sha",
            responses={
                provider_ids[0]: _response(provider_ids[0], "cmp-a"),
                provider_ids[1]: _response(provider_ids[1], "cmp-b"),
            },
        )

    monkeypatch.setattr(service.router, "invoke_comparative", _fake_comparative)
    comparative = service.execute_comparative(
        session_id=session_id,
        provider_ids=["openai", "gemini"],
        prompt="hello world",
    )
    assert len(comparative["traces"]) == 2
    assert len(comparative["epistemic_diffs"]) >= 1

    conn = sqlite3.connect(str(tmp_path / "kuro_playground.db"))
    diff_count = conn.execute("SELECT COUNT(*) FROM epistemic_diffs").fetchone()[0]
    conn.close()
    assert diff_count >= 1
