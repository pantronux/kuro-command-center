"""
Runtime registry for Kuro V2 runtime configuration.
"""

# --- Header Doc ---
# Purpose: Central registry for all Kuro runtime configurations.
#          Loads runtime YAML configs and provides lookup with sovereign fallback.
# Caller: runtime_context.py, main.py startup, /api/runtimes routes
# Dependencies: pyyaml, pydantic, pathlib
# Main Functions: RuntimeRegistry.get(), list_runtimes(), reload()
# Side Effects: Reads config/runtime/*.runtime.yaml at startup

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar, Optional

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

KURO_RUNTIME_CONFIG_VERSION = 1


class RuntimeConfig(BaseModel):
    runtime_id: str
    display_name: str
    version: int = 1
    memory_namespace: str
    retrieval_scope: list[str] = Field(default_factory=list)
    prompt_stack: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    structured_output_contract: Optional[str] = None
    allowed_providers: list[str] = Field(default_factory=lambda: ["gemini"])
    fallback_provider: str = "gemini"
    vocabulary_sanitization: bool = False
    is_stub: bool = False


class RuntimeRegistry:
    _cache: ClassVar[dict[str, RuntimeConfig]] = {}
    _config_dir: ClassVar[Path] = (
        Path(__file__).resolve().parents[2] / "config" / "runtime"
    )

    @classmethod
    def load_all(cls) -> None:
        cls._cache.clear()
        config_dir = cls._config_dir
        if not config_dir.exists():
            logger.warning("Runtime config directory does not exist: %s", config_dir)
        else:
            for yaml_file in sorted(config_dir.glob("*.runtime.yaml")):
                try:
                    data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
                    if not isinstance(data, dict):
                        raise ValueError("YAML root must be a mapping/object")
                    if data.get("version", 1) > KURO_RUNTIME_CONFIG_VERSION:
                        logger.warning(
                            "Runtime config %s version %s > supported %s, skipping",
                            yaml_file,
                            data.get("version", 1),
                            KURO_RUNTIME_CONFIG_VERSION,
                        )
                        continue
                    config = RuntimeConfig(**data)
                    cls._cache[config.runtime_id] = config
                    logger.info(
                        "Loaded runtime: %s v%s",
                        config.runtime_id,
                        config.version,
                    )
                except Exception as exc:
                    logger.error(
                        "Failed to load runtime config %s: %s",
                        yaml_file,
                        exc,
                    )
        if "sovereign" not in cls._cache:
            logger.critical("sovereign runtime config missing! Using hardcoded fallback.")
            cls._cache["sovereign"] = RuntimeConfig(
                runtime_id="sovereign",
                display_name="Sovereign Chat",
                memory_namespace="kuro.sovereign",
            )

    @classmethod
    def get(cls, runtime_id: str) -> RuntimeConfig:
        if not cls._cache:
            cls.load_all()
        config = cls._cache.get(runtime_id)
        if config is None:
            logger.warning(
                "Unknown runtime_id=%r, falling back to sovereign",
                runtime_id,
            )
            return cls._cache["sovereign"]
        return config

    @classmethod
    def list_runtimes(cls, include_stubs: bool = False) -> list[RuntimeConfig]:
        if not cls._cache:
            cls.load_all()
        return [c for c in cls._cache.values() if include_stubs or not c.is_stub]

    @classmethod
    def reload(cls) -> None:
        cls.load_all()
