"""Auth and feature policy for the KRC knowledge gateway."""
from __future__ import annotations

import hmac
import os
from typing import Any, Callable, Dict

from fastapi import HTTPException, Request


def _bearer_token(value: str) -> str:
    raw = (value or "").strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw


def _api_key_from_request(request: Request) -> str:
    return (
        request.headers.get("X-Kuro-Knowledge-Key")
        or request.headers.get("X-Kuro-Knowledge-API-Key")
        or _bearer_token(request.headers.get("Authorization", ""))
        or ""
    ).strip()


def candidate_writes_enabled() -> bool:
    return os.getenv("KURO_KRC_KNOWLEDGE_CANDIDATES_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def resolve_knowledge_actor(
    request: Request,
    *,
    cookie_auth_dependency: Callable[[Request], Dict[str, str]],
) -> Dict[str, Any]:
    """Resolve either a KKG API-key actor or an existing authenticated user."""
    configured_key = os.getenv("KURO_KNOWLEDGE_API_KEY", "").strip()
    supplied_key = _api_key_from_request(request)
    if configured_key and supplied_key and hmac.compare_digest(supplied_key, configured_key):
        return {
            "username": "knowledge_gateway",
            "auth_type": "api_key",
            "scopes": ["knowledge:read", "knowledge:candidate"],
        }

    try:
        user = cookie_auth_dependency(request)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Knowledge API authentication required.")
    return {
        "username": user.get("username", "unknown"),
        "auth_type": "cookie",
        "scopes": ["knowledge:read", "knowledge:candidate"],
    }
