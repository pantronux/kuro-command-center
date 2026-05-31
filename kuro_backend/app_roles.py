"""Product role resolution for the Kuro app family.

`KURO_APP_ROLE` is the product-level switch. `KURO_APP_PROFILE` remains a
compatibility input for older KRC deployments and tests.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


APP_ROLES: tuple[str, ...] = ("legacy", "krc", "kcc", "knowledge", "dev")

ROLE_LABELS: dict[str, str] = {
    "legacy": "Kuro AI",
    "krc": "Kuro Research Center",
    "kcc": "Kuro Command Center",
    "knowledge": "Kuro Knowledge",
    "dev": "Kuro Developer Workspace",
}

ROLE_PUBLIC_CAPABILITIES: dict[str, dict[str, bool]] = {
    "legacy": {
        "daily_chat": True,
        "research": False,
        "command_center": False,
        "knowledge_service": False,
    },
    "krc": {
        "daily_chat": False,
        "research": True,
        "command_center": False,
        "knowledge_service": False,
    },
    "kcc": {
        "daily_chat": False,
        "research": False,
        "command_center": True,
        "knowledge_service": False,
    },
    "knowledge": {
        "daily_chat": False,
        "research": False,
        "command_center": False,
        "knowledge_service": True,
    },
    "dev": {
        "daily_chat": True,
        "research": True,
        "command_center": True,
        "knowledge_service": True,
    },
}


def normalize_app_role(value: Optional[str]) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "research": "krc",
        "research-center": "krc",
        "kuro-research-center": "krc",
        "command": "kcc",
        "command-center": "kcc",
        "kuro-command-center": "kcc",
        "kk": "knowledge",
        "kuro-knowledge": "knowledge",
        "local-dev": "dev",
        "developer": "dev",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in APP_ROLES else "legacy"


def _role_from_profile() -> str:
    profile = str(os.getenv("KURO_APP_PROFILE", "legacy") or "legacy").strip().lower()
    if profile in {"krc", "dev"}:
        return profile
    return "legacy"


def get_app_role() -> str:
    """Return active product role, defaulting safely to legacy."""
    explicit = os.getenv("KURO_APP_ROLE")
    if explicit is not None and explicit.strip():
        return normalize_app_role(explicit)
    return _role_from_profile()


def is_legacy_role() -> bool:
    return get_app_role() == "legacy"


def is_krc_role() -> bool:
    return get_app_role() == "krc"


def is_kcc_role() -> bool:
    return get_app_role() == "kcc"


def is_knowledge_role() -> bool:
    return get_app_role() == "knowledge"


def is_dev_role() -> bool:
    return get_app_role() == "dev"


def get_workspace_label(role: Optional[str] = None) -> str:
    active = normalize_app_role(role) if role else get_app_role()
    return ROLE_LABELS.get(active, ROLE_LABELS["legacy"])


def get_app_role_snapshot(public: bool = False) -> Dict[str, Any]:
    role = get_app_role()
    payload: Dict[str, Any] = {
        "app_role": role,
        "workspace_label": get_workspace_label(role),
        "is_legacy": role == "legacy",
        "is_krc": role == "krc",
        "is_kcc": role == "kcc",
        "is_knowledge": role == "knowledge",
        "is_dev": role == "dev",
        "capabilities": dict(ROLE_PUBLIC_CAPABILITIES.get(role, {})),
    }
    if not public:
        payload["supported_roles"] = list(APP_ROLES)
        payload["env"] = {
            "role_env": "KURO_APP_ROLE",
            "profile_compat_env": "KURO_APP_PROFILE",
            "role_source": (
                "KURO_APP_ROLE"
                if os.getenv("KURO_APP_ROLE", "").strip()
                else "KURO_APP_PROFILE"
            ),
        }
    return payload
