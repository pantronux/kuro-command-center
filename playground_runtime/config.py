"""
KPR configuration.

--- Header Doc ---
Purpose: Separate BaseSettings-like configuration for KURO_PLAYGROUND_* flags and PLAYGROUND_* provider keys.
Caller: KPR API, provider registry, db bootstrap, tests.
Dependencies: os, dataclasses, pydantic optional.
Main Functions: PlaygroundSettings, get_settings().
Side Effects: Reads environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Optional


try:
    from pydantic_settings import BaseSettings as _BaseSettings  # type: ignore
except Exception:
    try:
        from pydantic import BaseSettings as _BaseSettings  # type: ignore
    except Exception:
        class _BaseSettings:  # fallback shim
            pass


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


@dataclass(frozen=True)
class ProviderEnvConfig:
    provider_id: str
    active: bool
    api_key: Optional[str]
    model_name: Optional[str]
    base_url: Optional[str]


class PlaygroundSettings(_BaseSettings):
    """KPR settings (isolated namespace only)."""

    KURO_PLAYGROUND_ENABLED: bool = _as_bool(os.getenv("KURO_PLAYGROUND_ENABLED"), False)
    KURO_PLAYGROUND_API_ENABLED: bool = _as_bool(os.getenv("KURO_PLAYGROUND_API_ENABLED"), False)
    KURO_PLAYGROUND_RESEARCH_MODE: bool = _as_bool(os.getenv("KURO_PLAYGROUND_RESEARCH_MODE"), False)
    KURO_PLAYGROUND_FORENSIC_MODE: bool = _as_bool(os.getenv("KURO_PLAYGROUND_FORENSIC_MODE"), False)
    KURO_PLAYGROUND_COMPARATIVE_MODE: bool = _as_bool(os.getenv("KURO_PLAYGROUND_COMPARATIVE_MODE"), False)
    KURO_PLAYGROUND_ONTOLOGY_MODE: bool = _as_bool(os.getenv("KURO_PLAYGROUND_ONTOLOGY_MODE"), False)
    KURO_PLAYGROUND_TELEMETRY_ENABLED: bool = _as_bool(os.getenv("KURO_PLAYGROUND_TELEMETRY_ENABLED"), False)
    KURO_PLAYGROUND_HALLUCINATION_ANALYZER: bool = _as_bool(os.getenv("KURO_PLAYGROUND_HALLUCINATION_ANALYZER"), False)
    KURO_PLAYGROUND_EPISTEMIC_DIFF: bool = _as_bool(os.getenv("KURO_PLAYGROUND_EPISTEMIC_DIFF"), False)
    KURO_PLAYGROUND_ONTOLOGY_RECONSTRUCTION: bool = _as_bool(os.getenv("KURO_PLAYGROUND_ONTOLOGY_RECONSTRUCTION"), False)
    KURO_PLAYGROUND_REPORT_EXPORT: bool = _as_bool(os.getenv("KURO_PLAYGROUND_REPORT_EXPORT"), False)
    KURO_PLAYGROUND_MAX_CONCURRENT_PROVIDERS: int = _as_int(os.getenv("KURO_PLAYGROUND_MAX_CONCURRENT_PROVIDERS"), 2)
    KURO_PLAYGROUND_RAW_EVIDENCE_RETENTION_DAYS: int = _as_int(
        os.getenv("KURO_PLAYGROUND_RAW_EVIDENCE_RETENTION_DAYS"), 90
    )
    KURO_PLAYGROUND_DB_PATH: str = os.getenv("KURO_PLAYGROUND_DB_PATH", "kuro_playground.db")
    KURO_PLAYGROUND_OTEL_ENDPOINT: str = os.getenv("KURO_PLAYGROUND_OTEL_ENDPOINT", "http://localhost:6006/v1/traces")
    KURO_PLAYGROUND_OTEL_PROJECT_NAME: str = os.getenv("KURO_PLAYGROUND_OTEL_PROJECT_NAME", "kuro-playground")
    KURO_PLAYGROUND_OTEL_SERVICE_NAME: str = os.getenv("KURO_PLAYGROUND_OTEL_SERVICE_NAME", "kuro-playground-runtime")
    KURO_PLAYGROUND_PROVIDER_HEALTH_INTERVAL_S: int = _as_int(
        os.getenv("KURO_PLAYGROUND_PROVIDER_HEALTH_INTERVAL_S"), 30
    )
    KURO_PLAYGROUND_PROVIDER_FAILURE_THRESHOLD: int = _as_int(
        os.getenv("KURO_PLAYGROUND_PROVIDER_FAILURE_THRESHOLD"), 3
    )
    PLAYGROUND_OPENAI_API_KEY: Optional[str] = os.getenv("PLAYGROUND_OPENAI_API_KEY")
    PLAYGROUND_OPENAI_MODEL_NAME: Optional[str] = os.getenv("PLAYGROUND_OPENAI_MODEL_NAME")
    PLAYGROUND_GEMINI_API_KEY: Optional[str] = os.getenv("PLAYGROUND_GEMINI_API_KEY")
    PLAYGROUND_GEMINI_MODEL_NAME: Optional[str] = os.getenv("PLAYGROUND_GEMINI_MODEL_NAME")
    PLAYGROUND_ANTHROPIC_API_KEY: Optional[str] = os.getenv("PLAYGROUND_ANTHROPIC_API_KEY")
    PLAYGROUND_ANTHROPIC_MODEL_NAME: Optional[str] = os.getenv("PLAYGROUND_ANTHROPIC_MODEL_NAME")
    PLAYGROUND_DEEPSEEK_API_KEY: Optional[str] = os.getenv("PLAYGROUND_DEEPSEEK_API_KEY")
    PLAYGROUND_DEEPSEEK_MODEL_NAME: Optional[str] = os.getenv("PLAYGROUND_DEEPSEEK_MODEL_NAME")
    PLAYGROUND_OLLAMA_BASE_URL: Optional[str] = os.getenv("PLAYGROUND_OLLAMA_BASE_URL")
    PLAYGROUND_OLLAMA_MODEL_NAME: Optional[str] = os.getenv("PLAYGROUND_OLLAMA_MODEL_NAME")
    PLAYGROUND_OPENAI_COMPAT_BASE_URL: Optional[str] = os.getenv("PLAYGROUND_OPENAI_COMPAT_BASE_URL")
    PLAYGROUND_OPENAI_COMPAT_API_KEY: Optional[str] = os.getenv("PLAYGROUND_OPENAI_COMPAT_API_KEY")
    PLAYGROUND_OPENAI_COMPAT_MODEL_NAME: Optional[str] = os.getenv("PLAYGROUND_OPENAI_COMPAT_MODEL_NAME")

    class Config:
        extra = "ignore"

    def snapshot_flags(self) -> Dict[str, object]:
        return {
            "KURO_PLAYGROUND_ENABLED": self.KURO_PLAYGROUND_ENABLED,
            "KURO_PLAYGROUND_API_ENABLED": self.KURO_PLAYGROUND_API_ENABLED,
            "KURO_PLAYGROUND_RESEARCH_MODE": self.KURO_PLAYGROUND_RESEARCH_MODE,
            "KURO_PLAYGROUND_FORENSIC_MODE": self.KURO_PLAYGROUND_FORENSIC_MODE,
            "KURO_PLAYGROUND_COMPARATIVE_MODE": self.KURO_PLAYGROUND_COMPARATIVE_MODE,
            "KURO_PLAYGROUND_ONTOLOGY_MODE": self.KURO_PLAYGROUND_ONTOLOGY_MODE,
            "KURO_PLAYGROUND_TELEMETRY_ENABLED": self.KURO_PLAYGROUND_TELEMETRY_ENABLED,
            "KURO_PLAYGROUND_HALLUCINATION_ANALYZER": self.KURO_PLAYGROUND_HALLUCINATION_ANALYZER,
            "KURO_PLAYGROUND_EPISTEMIC_DIFF": self.KURO_PLAYGROUND_EPISTEMIC_DIFF,
            "KURO_PLAYGROUND_ONTOLOGY_RECONSTRUCTION": self.KURO_PLAYGROUND_ONTOLOGY_RECONSTRUCTION,
            "KURO_PLAYGROUND_REPORT_EXPORT": self.KURO_PLAYGROUND_REPORT_EXPORT,
            "KURO_PLAYGROUND_MAX_CONCURRENT_PROVIDERS": self.KURO_PLAYGROUND_MAX_CONCURRENT_PROVIDERS,
            "KURO_PLAYGROUND_RAW_EVIDENCE_RETENTION_DAYS": self.KURO_PLAYGROUND_RAW_EVIDENCE_RETENTION_DAYS,
        }

    def provider_env_configs(self) -> Dict[str, ProviderEnvConfig]:
        """Return canonical provider config map from PLAYGROUND_* env namespace."""
        cfg: Dict[str, ProviderEnvConfig] = {
            "openai": ProviderEnvConfig(
                provider_id="openai",
                active=bool(self.PLAYGROUND_OPENAI_API_KEY and self.PLAYGROUND_OPENAI_API_KEY.strip()),
                api_key=self.PLAYGROUND_OPENAI_API_KEY,
                model_name=self.PLAYGROUND_OPENAI_MODEL_NAME,
                base_url=None,
            ),
            "gemini": ProviderEnvConfig(
                provider_id="gemini",
                active=bool(self.PLAYGROUND_GEMINI_API_KEY and self.PLAYGROUND_GEMINI_API_KEY.strip()),
                api_key=self.PLAYGROUND_GEMINI_API_KEY,
                model_name=self.PLAYGROUND_GEMINI_MODEL_NAME,
                base_url=None,
            ),
            "anthropic": ProviderEnvConfig(
                provider_id="anthropic",
                active=bool(self.PLAYGROUND_ANTHROPIC_API_KEY and self.PLAYGROUND_ANTHROPIC_API_KEY.strip()),
                api_key=self.PLAYGROUND_ANTHROPIC_API_KEY,
                model_name=self.PLAYGROUND_ANTHROPIC_MODEL_NAME,
                base_url=None,
            ),
            "deepseek": ProviderEnvConfig(
                provider_id="deepseek",
                active=bool(self.PLAYGROUND_DEEPSEEK_API_KEY and self.PLAYGROUND_DEEPSEEK_API_KEY.strip()),
                api_key=self.PLAYGROUND_DEEPSEEK_API_KEY,
                model_name=self.PLAYGROUND_DEEPSEEK_MODEL_NAME,
                base_url=None,
            ),
            "ollama": ProviderEnvConfig(
                provider_id="ollama",
                active=bool(self.PLAYGROUND_OLLAMA_BASE_URL and self.PLAYGROUND_OLLAMA_BASE_URL.strip()),
                api_key=None,
                model_name=self.PLAYGROUND_OLLAMA_MODEL_NAME,
                base_url=self.PLAYGROUND_OLLAMA_BASE_URL,
            ),
            "openai_compat": ProviderEnvConfig(
                provider_id="openai_compat",
                active=bool(self.PLAYGROUND_OPENAI_COMPAT_BASE_URL and self.PLAYGROUND_OPENAI_COMPAT_BASE_URL.strip()),
                api_key=self.PLAYGROUND_OPENAI_COMPAT_API_KEY,
                model_name=self.PLAYGROUND_OPENAI_COMPAT_MODEL_NAME,
                base_url=self.PLAYGROUND_OPENAI_COMPAT_BASE_URL,
            ),
        }
        return cfg


@lru_cache(maxsize=1)
def get_settings() -> PlaygroundSettings:
    return PlaygroundSettings()
