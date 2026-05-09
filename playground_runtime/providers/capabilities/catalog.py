"""Static capability extensions for forensic registry snapshots."""

from __future__ import annotations


def extend_capability_payload(provider_id: str, base_payload: dict) -> dict:
    payload = dict(base_payload)
    payload["provider"] = provider_id
    payload["supports_reasoning_artifacts"] = bool(payload.get("exposes_visible_reasoning_traces", False))
    payload["supports_signed_metadata"] = False
    return payload
