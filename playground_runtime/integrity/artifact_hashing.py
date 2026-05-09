"""Canonical hashing helpers for forensic artifacts."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


def canonical_json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def sha256_json(payload: Any) -> str:
    return sha256_text(canonical_json_dumps(payload))
