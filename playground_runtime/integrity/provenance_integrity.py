"""Provenance-related integrity helpers."""

from __future__ import annotations

from dataclasses import asdict

from playground_runtime.integrity.artifact_hashing import sha256_json
from playground_runtime.providers.schemas.capability_spec import CapabilitySpec


def capability_snapshot_payload(spec: CapabilitySpec) -> dict:
    payload = asdict(spec)
    payload["supports_reasoning_artifacts"] = bool(spec.exposes_visible_reasoning_traces)
    payload["supports_signed_metadata"] = False
    return payload


def capability_snapshot_hash(spec: CapabilitySpec) -> str:
    return sha256_json(capability_snapshot_payload(spec))
