from __future__ import annotations

import importlib
import sqlite3
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


def test_snapshot_verification_detects_tamper(tmp_path, monkeypatch):
    db_path = tmp_path / "kuro_playground.db"
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(db_path))
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("KURO_PLAYGROUND_HALLUCINATION_ANALYZER", "false")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())
    monkeypatch.setattr(service.router, "invoke_single", lambda provider_id, req: _response(provider_id, "result"))

    sid = service.create_session(mode="research", actor="Pantronux")["session_id"]
    exec_row = service.execute_single(session_id=sid, provider_id="openai", prompt="hello", actor="Pantronux")
    snap = service.create_snapshot(session_id=sid, execution_id=exec_row["execution_id"], actor="Pantronux")

    ok = service.verify_snapshot(session_id=sid, snapshot_id=snap["snapshot_id"], actor="Pantronux")
    assert ok["verification_status"] == "verified"

    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE evidence_snapshots SET snapshot_bundle_json='{}' WHERE snapshot_id=?", (snap["snapshot_id"],))
    conn.commit()
    conn.close()

    fail = service.verify_snapshot(session_id=sid, snapshot_id=snap["snapshot_id"], actor="Pantronux")
    assert fail["verification_status"] == "failed"
