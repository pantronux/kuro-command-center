"""Kuro Research Center profile flags and safe snapshots."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


APP_PROFILES: tuple[str, ...] = ("legacy", "krc", "dev")

KRC_FEATURE_DEFAULTS: dict[str, tuple[str, bool]] = {
    "research_console": ("KURO_KRC_RESEARCH_CONSOLE_ENABLED", True),
    "playground": ("KURO_KRC_PLAYGROUND_ENABLED", True),
    "qa_playground": ("KURO_KRC_QA_PLAYGROUND_ENABLED", False),
    "qa_productization": ("KURO_KRC_QA_PRODUCTIZATION_ENABLED", False),
    "knowledge_publish": ("KURO_KRC_KNOWLEDGE_PUBLISH_ENABLED", True),
    "ingestion": ("KURO_KRC_INGESTION_ENABLED", True),
    "evaluation": ("KURO_KRC_EVALUATION_ENABLED", False),
    "export": ("KURO_KRC_EXPORT_ENABLED", True),
    "daily_chat_prominent": ("KURO_KRC_DAILY_CHAT_PROMINENT", False),
    "telegram_center": ("KURO_KRC_TELEGRAM_CENTER_ENABLED", True),
    "market": ("KURO_KRC_MARKET_ENABLED", False),
    "agent_tools": ("KURO_KRC_AGENT_TOOLS_ENABLED", False),
    "daily_tasks": ("KURO_KRC_DAILY_TASKS_ENABLED", False),
    "proactive_events": ("KURO_KRC_PROACTIVE_EVENTS_ENABLED", False),
}

KRC_SCHEDULER_DEFAULTS: dict[str, tuple[str, bool]] = {
    "backup": ("KURO_KRC_SCHEDULER_BACKUP_ENABLED", True),
    "memory_decay": ("KURO_KRC_SCHEDULER_MEMORY_DECAY_ENABLED", True),
    "evaluation": ("KURO_KRC_SCHEDULER_EVALUATION_ENABLED", False),
    "market": ("KURO_KRC_SCHEDULER_MARKET_ENABLED", False),
    "telegram": ("KURO_KRC_SCHEDULER_TELEGRAM_ENABLED", True),
    "proactive": ("KURO_KRC_SCHEDULER_PROACTIVE_ENABLED", False),
    "fitness": ("KURO_KRC_SCHEDULER_FITNESS_ENABLED", False),
    "daily_briefing": ("KURO_KRC_SCHEDULER_DAILY_BRIEFING_ENABLED", False),
    "file_retention": ("KURO_KRC_SCHEDULER_FILE_RETENTION_ENABLED", True),
}

_FEATURE_ALIASES: dict[str, str] = {
    "console": "research_console",
    "research": "research_console",
    "research_playground": "playground",
    "qa": "qa_playground",
    "qa_product": "qa_productization",
    "qa_productization_track": "qa_productization",
    "knowledge": "knowledge_publish",
    "knowledge_api": "knowledge_publish",
    "documents": "ingestion",
    "reports": "export",
    "telegram": "telegram_center",
    "market_sentinel": "market",
    "tasks": "daily_tasks",
}

_PUBLIC_FEATURES: tuple[str, ...] = (
    "research_console",
    "playground",
    "qa_playground",
    "qa_productization",
    "knowledge_publish",
    "ingestion",
    "evaluation",
    "export",
    "market",
    "telegram_center",
)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_app_profile(value: Optional[str]) -> str:
    """Normalize profile names to legacy/krc/dev with legacy as fallback."""
    normalized = str(value or "").strip().lower()
    return normalized if normalized in APP_PROFILES else "legacy"


def get_app_profile() -> str:
    """Return the active app profile, defaulting to legacy."""
    return normalize_app_profile(os.getenv("KURO_APP_PROFILE", "legacy"))


def is_krc_profile() -> bool:
    """Return True only when KRC mode is explicitly active."""
    return get_app_profile() == "krc"


def is_dev_profile() -> bool:
    """Return True for the all-features-visible debug profile."""
    return get_app_profile() == "dev"


def _normalize_feature_name(name: str) -> Optional[str]:
    cleaned = str(name or "").strip().lower()
    if not cleaned:
        return None
    cleaned = cleaned.removeprefix("kuro_krc_")
    cleaned = cleaned.removesuffix("_enabled")
    cleaned = cleaned.removesuffix("_flag")
    cleaned = _FEATURE_ALIASES.get(cleaned, cleaned)
    return cleaned if cleaned in KRC_FEATURE_DEFAULTS else None


def _raw_feature_flag(name: str) -> bool:
    env_name, default = KRC_FEATURE_DEFAULTS[name]
    return _env_bool(env_name, default)


def is_krc_feature_enabled(name: str) -> bool:
    """Return an effective KRC feature flag.

    Legacy profile keeps KRC-only behavior inactive even when raw KRC defaults
    are true. Dev profile intentionally reports every known KRC feature as
    enabled for local debugging.
    """
    normalized = _normalize_feature_name(name)
    if not normalized:
        return False
    profile = get_app_profile()
    if profile == "dev":
        return True
    if profile != "krc":
        return False
    return _raw_feature_flag(normalized)


def _normalize_scheduler_name(name: str) -> Optional[str]:
    cleaned = str(name or "").strip().lower()
    if not cleaned:
        return None
    cleaned = cleaned.removeprefix("kuro_krc_scheduler_")
    cleaned = cleaned.removesuffix("_enabled")
    aliases = {
        "memory": "memory_decay",
        "retention": "file_retention",
        "telegram_retry": "telegram",
        "telegram_digest": "telegram",
        "dreaming": "proactive",
        "hardware": "proactive",
        "price_ticker": "market",
        "market_sentinel": "market",
    }
    cleaned = aliases.get(cleaned, cleaned)
    return cleaned if cleaned in KRC_SCHEDULER_DEFAULTS else None


def is_krc_scheduler_enabled(name: str) -> bool:
    """Return scheduler availability with legacy behavior preserved."""
    normalized = _normalize_scheduler_name(name)
    if not normalized:
        return False
    profile = get_app_profile()
    if profile == "dev":
        return True
    if profile != "krc":
        return True
    env_name, default = KRC_SCHEDULER_DEFAULTS[normalized]
    return _env_bool(env_name, default)


def get_krc_profile_snapshot(public: bool = False) -> Dict[str, Any]:
    """Return a secret-free KRC profile snapshot.

    Public snapshots expose only product capabilities. Admin snapshots include
    raw flag defaults and environment variable names so operators can verify
    rollback and profile behavior without leaking secrets.
    """
    profile = get_app_profile()
    feature_names = _PUBLIC_FEATURES if public else tuple(KRC_FEATURE_DEFAULTS)
    effective_features = {
        feature: is_krc_feature_enabled(feature)
        for feature in feature_names
    }
    payload: Dict[str, Any] = {
        "app_profile": profile,
        "is_krc": profile == "krc",
        "is_dev": profile == "dev",
        "workspace_label": (
            "Kuro Research Center"
            if profile in {"krc", "dev"}
            else "Kuro AI"
        ),
        "features": effective_features,
    }
    if not public:
        payload["supported_profiles"] = list(APP_PROFILES)
        payload["raw_flags"] = {
            feature: {
                "env": env_name,
                "default": default,
                "raw_enabled": _raw_feature_flag(feature),
                "effective_enabled": effective_features[feature],
            }
            for feature, (env_name, default) in KRC_FEATURE_DEFAULTS.items()
        }
        payload["scheduler_flags"] = {
            name: {
                "env": env_name,
                "default": default,
                "effective_enabled": is_krc_scheduler_enabled(name),
            }
            for name, (env_name, default) in KRC_SCHEDULER_DEFAULTS.items()
        }
    return payload
