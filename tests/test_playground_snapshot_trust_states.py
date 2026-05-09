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


def test_snapshot_trust_states_mapping_and_summary_text(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "kuro_playground.db"))
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())
    monkeypatch.setattr(service.router, "invoke_single", lambda provider_id, req: _response(provider_id, "ok"))

    sid = service.create_session(mode="forensic", actor="Pantronux")["session_id"]
    result = service.execute_single(session_id=sid, provider_id="openai", prompt="verify me", actor="Pantronux")

    snapshot = service.create_snapshot(session_id=sid, execution_id=result["execution_id"], actor="Pantronux")
    snapshot_id = snapshot["snapshot_id"]

    summary_unverified = service.build_snapshot_trust_summary(session_id=sid, snapshot_id=snapshot_id)
    assert summary_unverified["snapshot_integrity"] == "UNVERIFIED"
    assert "not been verified" in summary_unverified["summary_text"]

    verified = service.verify_snapshot(session_id=sid, snapshot_id=snapshot_id, actor="Pantronux")
    assert verified["verification_status"] == "verified"
    assert verified["trust_summary"]["snapshot_integrity"] == "VALID"
    assert "VALID" in verified["trust_summary"]["summary_text"]

    service.db.update_evidence_snapshot_verification(snapshot_id, "partial")
    summary_partial = service.build_snapshot_trust_summary(session_id=sid, snapshot_id=snapshot_id)
    assert summary_partial["snapshot_integrity"] == "PARTIAL"

    service.db.update_evidence_snapshot_verification(snapshot_id, "failed")
    summary_corrupted = service.build_snapshot_trust_summary(session_id=sid, snapshot_id=snapshot_id)
    assert summary_corrupted["snapshot_integrity"] == "CORRUPTED"
    assert summary_corrupted["replay_compatibility"] == "NO"
