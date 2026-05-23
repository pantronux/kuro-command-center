"""Deployment profile metadata for small-enterprise Kuro operations."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Tuple


STABLE_RUNTIME_FLAGS: Dict[str, bool] = {
    "KURO_PLAYGROUND_ENABLED": True,
    "KURO_PLAYGROUND_API_ENABLED": True,
    "KURO_V2_STRICT_MODE": True,
    "KURO_PROVIDER_ROUTER_ENABLED": True,
    "KURO_DEV_MODE": False,
    "KURO_ENTERPRISE_REFACTOR_ENABLED": True,
    "KURO_MEMORY_V3_ENABLED": True,
    "KURO_STORAGE_V2_ENABLED": True,
    "KURO_CHAT_V2_ENABLED": True,
    "KURO_MARKET_SENTINEL_V2_ENABLED": True,
    "KURO_TELEGRAM_V2_ENABLED": True,
    "KURO_PROVIDER_REGISTRY_V2_ENABLED": True,
    "KURO_AGENT_TOOLS_V2_ENABLED": True,
    "KURO_TASKS_V2_ENABLED": True,
    "KURO_DEEP_RESEARCH_V2_ENABLED": True,
    "KURO_WEB_SEARCH_V2_ENABLED": True,
    "KURO_ADMIN_SETTINGS_V2_ENABLED": True,
    "KURO_ENTERPRISE_OBSERVABILITY_ENABLED": True,
    "KURO_API_V2_ENABLED": True,
    "OPENCLAW_ENABLED": False,
}


@dataclass(frozen=True)
class DeploymentProfile:
    profile_id: str
    label: str
    description: str
    required_env: Tuple[str, ...] = field(default_factory=tuple)
    optional_env: Tuple[str, ...] = field(default_factory=tuple)
    recommended_flags: Dict[str, bool] = field(default_factory=dict)
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def public_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "description": self.description,
            "required_env": list(self.required_env),
            "optional_env": list(self.optional_env),
            "recommended_flags": dict(self.recommended_flags),
            "notes": list(self.notes),
        }


DEPLOYMENT_PROFILES: Dict[str, DeploymentProfile] = {
    "local-dev": DeploymentProfile(
        profile_id="local-dev",
        label="Local Development",
        description="Single developer machine with local SQLite files and feature flags mostly off.",
        required_env=("JWT_SECRET_KEY",),
        optional_env=("GEMINI_API_KEY", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "SERPER_API_KEY"),
        recommended_flags={
            "KURO_API_V2_ENABLED": False,
            "KURO_ENTERPRISE_OBSERVABILITY_ENABLED": False,
        },
        notes=("Never commit .env.", "Use placeholder values in .env.example only."),
    ),
    "single-vm": DeploymentProfile(
        profile_id="single-vm",
        label="Single VM",
        description="Small production pilot on one VM with persistent volumes and systemd or process supervisor.",
        required_env=("JWT_SECRET_KEY", "WORKING_DIR"),
        optional_env=("GEMINI_API_KEY", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "SERPER_API_KEY"),
        recommended_flags={
            **STABLE_RUNTIME_FLAGS,
            "KURO_BACKUP_ENABLED": True,
        },
        notes=("Mount WORKING_DIR and backups on persistent storage.", "Restrict Phoenix to trusted networks."),
    ),
    "docker-compose": DeploymentProfile(
        profile_id="docker-compose",
        label="Docker Compose",
        description="One app container with optional Phoenix service and bind-mounted runtime state.",
        required_env=("JWT_SECRET_KEY", "WORKING_DIR"),
        optional_env=("GEMINI_API_KEY", "OPENAI_API_KEY", "TELEGRAM_TOKEN", "SERPER_API_KEY"),
        recommended_flags={
            "KURO_API_V2_ENABLED": True,
            "KURO_BACKUP_ENABLED": True,
        },
        notes=("Use docker-compose.yml with env_file=.env.", "Do not place real secrets in compose files."),
    ),
    "staging": DeploymentProfile(
        profile_id="staging",
        label="Staging",
        description="Pre-production environment for release checks and integration smoke tests.",
        required_env=("JWT_SECRET_KEY", "WORKING_DIR"),
        optional_env=("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "SERPER_API_KEY"),
        recommended_flags={
            **STABLE_RUNTIME_FLAGS,
        },
        notes=("Use non-production Telegram chats.", "Run backup restore verification before promotion."),
    ),
    "enterprise-pilot": DeploymentProfile(
        profile_id="enterprise-pilot",
        label="Enterprise Pilot",
        description="Small customer pilot with admin-only operations and documented incident response.",
        required_env=("JWT_SECRET_KEY", "WORKING_DIR"),
        optional_env=(
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "DEEPSEEK_API_KEY",
            "SERPER_API_KEY",
            "TELEGRAM_TOKEN",
            "TELEGRAM_CHAT_ID",
        ),
        recommended_flags={
            **STABLE_RUNTIME_FLAGS,
            "KURO_BACKUP_ENABLED": True,
        },
        notes=("Review secrets rotation.", "Verify backups and admin access before go-live."),
    ),
}


def normalize_profile_id(profile_id: str | None) -> str:
    normalized = (profile_id or os.getenv("KURO_DEPLOYMENT_PROFILE") or "local-dev").strip().lower()
    return normalized if normalized in DEPLOYMENT_PROFILES else "local-dev"


def get_deployment_profile(profile_id: str | None = None) -> DeploymentProfile:
    return DEPLOYMENT_PROFILES[normalize_profile_id(profile_id)]
