"""Evidence snapshot bundle helpers."""

from __future__ import annotations

from typing import Any

from playground_runtime.integrity.artifact_hashing import sha256_json


def build_snapshot_bundle(
    *,
    session_id: str,
    execution_id: str | None,
    raw_evidence: list[dict],
    canonical_traces: list[dict],
    transformation_manifests: list[dict],
    integrity_rows: list[dict],
    provider_capabilities: list[dict],
    runtime_config: dict,
) -> tuple[dict[str, Any], str]:
    bundle: dict[str, Any] = {
        "session_id": session_id,
        "execution_id": execution_id,
        "raw_evidence": raw_evidence,
        "canonical_traces": canonical_traces,
        "transformation_manifests": transformation_manifests,
        "integrity_rows": integrity_rows,
        "provider_capabilities": provider_capabilities,
        "runtime_config": runtime_config,
    }
    return bundle, sha256_json(bundle)
