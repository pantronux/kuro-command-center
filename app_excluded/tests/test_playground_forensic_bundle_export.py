from __future__ import annotations

import importlib
import zipfile
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


def test_forensic_bundle_export_zip_and_audit_records(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "kuro_playground.db"))
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())
    monkeypatch.setattr(service.router, "invoke_single", lambda provider_id, req: _response(provider_id, "ok"))

    sid = service.create_session(mode="forensic", actor="Pantronux")["session_id"]
    result = service.execute_single(session_id=sid, provider_id="openai", prompt="bundle", actor="Pantronux")
    service.create_snapshot(session_id=sid, execution_id=result["execution_id"], actor="Pantronux")

    output_path = tmp_path / "forensic_bundle.zip"
    exported = service.export_forensic_bundle(session_id=sid, output_path=str(output_path), actor="Pantronux")
    bundle_path = Path(exported["bundle"]["bundle_path"])
    assert bundle_path.exists()
    assert bundle_path == output_path

    with zipfile.ZipFile(bundle_path, "r") as archive:
        names = set(archive.namelist())
    assert any(name.startswith("raw/") for name in names)
    assert any(name.startswith("canonical/") for name in names)
    assert any(name.startswith("manifests/") for name in names)
    assert "hashes/integrity_ledger.json" in names
    assert "custody/chain_of_custody.json" in names
    assert "ontology/ontology.json" in names
    assert "ontology/jsonld.json" in names
    assert "ontology/rdf_star.json" in names
    assert "reports/reports.json" in names
    assert "reports/summary.md" in names

    integrity_rows = service.db.list_artifact_integrity(sid)
    assert any(row.get("artifact_type") == "forensic_bundle_zip" for row in integrity_rows)

    custody_rows = service.db.list_chain_of_custody(artifact_id=sid)
    assert any(row.get("action_type") == "FORENSIC_BUNDLE_EXPORTED" for row in custody_rows)
