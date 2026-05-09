"""Verification helpers for forensic integrity checks."""

from __future__ import annotations

from playground_runtime.integrity.artifact_hashing import sha256_json, sha256_text


def verify_hash(*, expected_sha256: str, payload: object | None = None, text: str | None = None) -> dict:
    if text is not None:
        actual = sha256_text(text)
    else:
        actual = sha256_json(payload)
    return {
        "expected_sha256": expected_sha256,
        "actual_sha256": actual,
        "verified": actual == expected_sha256,
    }
