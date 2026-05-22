"""Startup environment validation with secret-safe diagnostics."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from kuro_backend.enterprise_ops.deployment_profiles import get_deployment_profile


PROVIDER_KEYS = (
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
)

OPTIONAL_INTEGRATION_KEYS = (
    "TELEGRAM_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_WEBHOOK_SECRET",
    "SERPER_API_KEY",
    "OPENCLAW_BASE_URL",
    "OPENCLAW_API_KEY",
    "NEWSAPI_API_KEY",
    "METACULUS_API_TOKEN",
    "NVD_API_KEY",
)

REQUIRED_LOCAL_KEYS = ("JWT_SECRET_KEY",)


@dataclass(frozen=True)
class StartupValidationResult:
    profile_id: str
    ok: bool
    missing_required: List[str] = field(default_factory=list)
    missing_optional: List[str] = field(default_factory=list)
    configured_optional: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def public_dict(self) -> Dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "ok": self.ok,
            "missing_required": list(self.missing_required),
            "missing_optional": list(self.missing_optional),
            "configured_optional": list(self.configured_optional),
            "warnings": list(self.warnings),
        }


def _is_configured(key: str, environ: Dict[str, str]) -> bool:
    return bool(str(environ.get(key) or "").strip())


def _ordered_unique(values: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(value for value in values if value))


def validate_startup_environment(
    *,
    profile_id: Optional[str] = None,
    environ: Optional[Dict[str, str]] = None,
) -> StartupValidationResult:
    env = dict(environ or os.environ)
    profile = get_deployment_profile(profile_id or env.get("KURO_DEPLOYMENT_PROFILE"))
    required = _ordered_unique([*REQUIRED_LOCAL_KEYS, *profile.required_env])
    optional = _ordered_unique([*PROVIDER_KEYS, *OPTIONAL_INTEGRATION_KEYS, *profile.optional_env])

    missing_required = [key for key in required if not _is_configured(key, env)]
    missing_optional = [key for key in optional if not _is_configured(key, env)]
    configured_optional = [key for key in optional if _is_configured(key, env)]
    warnings: List[str] = []
    if not env.get("WORKING_DIR"):
        warnings.append("WORKING_DIR is not set; runtime state may default to process paths.")
    if not env.get("KURO_BACKUP_DIR"):
        warnings.append("KURO_BACKUP_DIR is not set; backup_manager will use its default.")

    return StartupValidationResult(
        profile_id=profile.profile_id,
        ok=not missing_required,
        missing_required=missing_required,
        missing_optional=missing_optional,
        configured_optional=configured_optional,
        warnings=warnings,
    )


def log_startup_validation(
    result: StartupValidationResult,
    logger: logging.Logger,
    *,
    fail_on_error: bool = True,
) -> None:
    logger.info("STARTUP: Deployment profile=%s", result.profile_id)
    for key in result.missing_required:
        logger.critical("STARTUP: Required env var %s is not set.", key)
    for key in result.missing_optional:
        logger.warning("STARTUP: Optional env var %s is not set.", key)
    for key in result.configured_optional:
        logger.info("STARTUP: Optional env var %s is configured.", key)
    for warning in result.warnings:
        logger.warning("STARTUP: %s", warning)
    if fail_on_error and result.missing_required:
        missing = ", ".join(result.missing_required)
        raise RuntimeError(f"Startup validation failed; missing required env vars: {missing}")
