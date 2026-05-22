"""Enterprise refactor feature flags and safe capability snapshots."""
from __future__ import annotations

from typing import Any, Dict, Optional

from kuro_backend.config import settings


ENTERPRISE_FLAG_NAMES: tuple[str, ...] = (
    "KURO_ENTERPRISE_REFACTOR_ENABLED",
    "KURO_MEMORY_V3_ENABLED",
    "KURO_STORAGE_V2_ENABLED",
    "KURO_CHAT_V2_ENABLED",
    "KURO_MARKET_SENTINEL_V2_ENABLED",
    "KURO_TELEGRAM_V2_ENABLED",
    "KURO_PROVIDER_REGISTRY_V2_ENABLED",
    "KURO_AGENT_TOOLS_V2_ENABLED",
    "KURO_TASKS_V2_ENABLED",
    "KURO_DEEP_RESEARCH_V2_ENABLED",
    "KURO_WEB_SEARCH_V2_ENABLED",
    "KURO_FRONTEND_V2_ENABLED",
    "KURO_ADMIN_SETTINGS_V2_ENABLED",
    "KURO_ENTERPRISE_OBSERVABILITY_ENABLED",
    "KURO_API_V2_ENABLED",
)

_PROVIDER_KEY_ATTRS: dict[str, str] = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

_MODEL_ALIAS_ATTRS: dict[str, str] = {
    "gemini_fast": "KURO_MODEL_GEMINI_FAST",
    "openai_nano": "KURO_MODEL_OPENAI_NANO",
    "claude_fast": "KURO_MODEL_CLAUDE_FAST",
    "deepseek_fast": "KURO_MODEL_DEEPSEEK_FAST",
}


def _normalize_flag_name(flag_name: str) -> Optional[str]:
    normalized = (flag_name or "").strip().upper()
    if normalized in ENTERPRISE_FLAG_NAMES:
        return normalized
    if normalized and not normalized.startswith("KURO_"):
        prefixed = f"KURO_{normalized}"
        if prefixed in ENTERPRISE_FLAG_NAMES:
            return prefixed
    return None


def _has_value(value: Any) -> bool:
    return bool(str(value or "").strip())


def is_enabled(flag_name: str) -> bool:
    """Return True only for known enterprise flags that are explicitly enabled."""
    normalized = _normalize_flag_name(flag_name)
    if not normalized:
        return False
    return bool(getattr(settings, normalized, False))


def require_feature_enabled(flag_name: str) -> Dict[str, Any]:
    """Return a safe structured status for callers that gate future V2 paths."""
    normalized = _normalize_flag_name(flag_name)
    if normalized and is_enabled(normalized):
        return {
            "enabled": True,
            "flag": normalized,
            "error": None,
        }
    return {
        "enabled": False,
        "flag": normalized or "UNKNOWN_FEATURE_FLAG",
        "error": {
            "code": "FEATURE_DISABLED",
            "message": "Requested enterprise feature is disabled.",
        },
    }


def _provider_availability() -> Dict[str, Dict[str, bool]]:
    return {
        provider: {"configured": _has_value(getattr(settings, attr, ""))}
        for provider, attr in _PROVIDER_KEY_ATTRS.items()
    }


def _model_alias_snapshot() -> Dict[str, str]:
    return {
        alias: str(getattr(settings, attr, "") or "")
        for alias, attr in _MODEL_ALIAS_ATTRS.items()
    }


def get_enterprise_flag_snapshot(admin: bool = False) -> Dict[str, Any]:
    """Return enterprise flag status.

    Public callers receive only high-level availability. Admin callers receive
    full flag names plus non-secret provider/key presence metadata.
    """
    flags = {flag: is_enabled(flag) for flag in ENTERPRISE_FLAG_NAMES}
    if admin:
        return {
            "enterprise_refactor_enabled": flags["KURO_ENTERPRISE_REFACTOR_ENABLED"],
            "flags": flags,
            "providers": _provider_availability(),
            "defaults": {
                "provider": str(getattr(settings, "KURO_DEFAULT_PROVIDER", "gemini") or "gemini"),
                "model_alias": str(getattr(settings, "KURO_DEFAULT_MODEL_ALIAS", "gemini_fast") or "gemini_fast"),
            },
            "model_aliases": _model_alias_snapshot(),
        }

    return {
        "enterprise_refactor_enabled": flags["KURO_ENTERPRISE_REFACTOR_ENABLED"],
        "features": {
            "chat": {
                "available": True,
                "v2_enabled": flags["KURO_CHAT_V2_ENABLED"],
            },
            "memory": {
                "available": True,
                "v2_enabled": flags["KURO_MEMORY_V3_ENABLED"],
            },
            "storage": {
                "available": True,
                "v2_enabled": flags["KURO_STORAGE_V2_ENABLED"],
            },
            "market_sentinel": {
                "available": bool(getattr(settings, "KURO_MARKET_SENTINEL_ENABLED", True)),
                "v2_enabled": flags["KURO_MARKET_SENTINEL_V2_ENABLED"],
            },
            "telegram": {
                "available": bool(getattr(settings, "KURO_TELEGRAM_ENABLED", True)),
                "v2_enabled": flags["KURO_TELEGRAM_V2_ENABLED"],
            },
            "provider_registry": {
                "available": False,
                "v2_enabled": flags["KURO_PROVIDER_REGISTRY_V2_ENABLED"],
            },
            "agent_actions": {
                "available": False,
                "v2_enabled": flags["KURO_AGENT_TOOLS_V2_ENABLED"],
            },
            "tasks": {
                "available": False,
                "v2_enabled": flags["KURO_TASKS_V2_ENABLED"],
            },
            "deep_research": {
                "available": bool(getattr(settings, "KURO_ADVISOR_AUTO_SEARCH", True)),
                "v2_enabled": flags["KURO_DEEP_RESEARCH_V2_ENABLED"],
            },
            "web_search": {
                "available": bool(getattr(settings, "KURO_ADVISOR_AUTO_SEARCH", True)),
                "v2_enabled": flags["KURO_WEB_SEARCH_V2_ENABLED"],
            },
            "frontend": {
                "available": True,
                "v2_enabled": flags["KURO_FRONTEND_V2_ENABLED"],
            },
            "admin_settings": {
                "available": False,
                "v2_enabled": flags["KURO_ADMIN_SETTINGS_V2_ENABLED"],
            },
            "observability": {
                "available": True,
                "v2_enabled": flags["KURO_ENTERPRISE_OBSERVABILITY_ENABLED"],
            },
            "api": {
                "available": True,
                "v2_enabled": flags["KURO_API_V2_ENABLED"],
            },
        },
    }
