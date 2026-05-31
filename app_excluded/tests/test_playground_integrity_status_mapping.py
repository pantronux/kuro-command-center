from __future__ import annotations

import importlib

from playground_runtime.service import PlaygroundRuntimeService


def _reload_config_module():
    import playground_runtime.config as config_module

    importlib.reload(config_module)
    config_module.get_settings.cache_clear()
    return config_module


def test_integrity_status_mapping_matrix(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "kuro_playground.db"))
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())

    assert service._map_execution_integrity_status(
        raw_integrity={"verification_status": "verified"},
        canonical_integrity={"verification_status": "verified"},
        trace_warnings=[],
        snapshot_trust={"snapshot_integrity": "CORRUPTED"},
    ) == "CORRUPTED"

    assert service._map_execution_integrity_status(
        raw_integrity={"verification_status": "unverified"},
        canonical_integrity={"verification_status": "verified"},
        trace_warnings=[],
        snapshot_trust=None,
    ) == "UNVERIFIED"

    assert service._map_execution_integrity_status(
        raw_integrity={"verification_status": "verified"},
        canonical_integrity={"verification_status": "verified"},
        trace_warnings=[],
        snapshot_trust={"snapshot_integrity": "PARTIAL"},
    ) == "PARTIAL"

    assert service._map_execution_integrity_status(
        raw_integrity={"verification_status": "verified"},
        canonical_integrity={"verification_status": "verified"},
        trace_warnings=["SCHEMA_DRIFT:response_text"],
        snapshot_trust=None,
    ) == "DRIFTED"

    assert service._map_execution_integrity_status(
        raw_integrity={"verification_status": "verified"},
        canonical_integrity={"verification_status": "verified"},
        trace_warnings=[],
        snapshot_trust={"snapshot_integrity": "DRIFTED"},
    ) == "MODIFIED"

    assert service._map_execution_integrity_status(
        raw_integrity={"verification_status": "verified"},
        canonical_integrity={"verification_status": "verified"},
        trace_warnings=[],
        snapshot_trust={"snapshot_integrity": "VALID"},
    ) == "VERIFIED"
