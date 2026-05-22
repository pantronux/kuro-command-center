"""OpenAPI helpers for API V2 public/admin separation."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


def route_is_admin_path(path: str) -> bool:
    normalized = path or ""
    return normalized.startswith("/api/admin") or "/admin/" in normalized


def public_openapi_schema(app: FastAPI) -> Dict[str, Any]:
    schema = get_openapi(
        title=app.title,
        version=getattr(app, "version", "0.1.0"),
        routes=app.routes,
    )
    public_schema = deepcopy(schema)
    public_paths = {}
    for path, operations in (schema.get("paths") or {}).items():
        if route_is_admin_path(path):
            continue
        public_paths[path] = operations
    public_schema["paths"] = public_paths
    return public_schema


def api_v2_tags() -> list[dict[str, str]]:
    return [
        {"name": "api-v2", "description": "Additive API V2 control plane."},
        {"name": "api-v2-admin", "description": "Admin-only API V2 diagnostics."},
    ]
