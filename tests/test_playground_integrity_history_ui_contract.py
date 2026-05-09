from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path

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


def test_history_contract_has_integrity_blocks_and_ui_hooks(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "kuro_playground.db"))
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())
    monkeypatch.setattr(service.router, "invoke_single", lambda provider_id, req: _response(provider_id, "ok"))

    sid = service.create_session(mode="forensic", actor="Pantronux")["session_id"]
    result = service.execute_single(session_id=sid, provider_id="openai", prompt="history", actor="Pantronux")
    service.create_snapshot(session_id=sid, execution_id=result["execution_id"], actor="Pantronux")

    history = service.get_session_history(session_id=sid)
    assert isinstance(history.get("integrity_overview"), dict)
    assert isinstance(history.get("session_timeline_integrity"), dict)
    assert isinstance(history.get("execution_integrity_rows"), list)
    assert isinstance(history.get("snapshot_trust_rows"), list)

    html = Path("web_interface/templates/index.html").read_text(encoding="utf-8")
    js = Path("web_interface/static/js/app.js").read_text(encoding="utf-8")

    assert "playgroundWorkflowModeSelect" in html
    assert "playgroundIntegrityOverview" in html
    assert "playgroundArtifactDrawer" in html
    assert "playgroundOpenIntegrityDetail" in js
    assert "playgroundLoadIntegrityOverview" in js
    assert "playgroundOutput.textContent" in js
