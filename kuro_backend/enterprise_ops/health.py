"""Public-safe liveness, readiness, and health payloads."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

from kuro_backend.enterprise_ops.deployment_profiles import get_deployment_profile
from kuro_backend.enterprise_ops.startup_validation import validate_startup_environment


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_backup_summary() -> Dict[str, Any]:
    try:
        from kuro_backend import backup_manager

        health = backup_manager.get_backup_health()
        return {
            "configured": bool(health.get("configured", False)),
            "last_status": health.get("last_status") or "unknown",
            "last_backup_age_hours": health.get("last_backup_age_hours"),
            "restore_docs_available": bool(health.get("restore_docs_available", False)),
        }
    except Exception:
        return {
            "configured": False,
            "last_status": "unknown",
            "last_backup_age_hours": None,
            "restore_docs_available": False,
        }


def build_live_payload() -> Dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "service": "kuro-ai",
            "live": True,
            "timestamp": _now_iso(),
        },
        "error": None,
    }


def build_ready_payload() -> Dict[str, Any]:
    profile = get_deployment_profile()
    validation = validate_startup_environment(profile_id=profile.profile_id)
    backup = _safe_backup_summary()
    ready = bool(validation.ok)
    checks = {
        "startup_environment": "ok" if validation.ok else "failed",
        "auth_signing_key": "configured" if os.getenv("JWT_SECRET_KEY") else "missing",
        "backup": "ok" if backup.get("configured") else "degraded",
    }
    return {
        "status": "success" if ready else "error",
        "data": {
            "service": "kuro-ai",
            "ready": ready,
            "profile": profile.profile_id,
            "timestamp": _now_iso(),
            "checks": checks,
            "backup": backup,
        },
        "error": None if ready else {"code": "not_ready", "message": "Required startup settings are missing."},
    }


def build_health_payload() -> Dict[str, Any]:
    live = build_live_payload()["data"]
    ready = build_ready_payload()["data"]
    return {
        "status": "success" if ready.get("ready") else "error",
        "data": {
            "service": "kuro-ai",
            "live": bool(live.get("live")),
            "ready": bool(ready.get("ready")),
            "profile": ready.get("profile"),
            "timestamp": _now_iso(),
            "checks": ready.get("checks", {}),
        },
        "error": None if ready.get("ready") else {"code": "not_ready", "message": "Readiness checks failed."},
    }
