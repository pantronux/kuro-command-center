"""Deployment, startup validation, backup, and health endpoint tests."""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WORKING_DIR", str(PROJECT_ROOT))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *args, **kwargs):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

if "phoenix" not in sys.modules:
    fake_phoenix = types.ModuleType("phoenix")

    class _FakePhoenixApp:
        url = "http://localhost:6006"

        def close(self):
            return None

    fake_phoenix.launch_app = lambda *args, **kwargs: _FakePhoenixApp()
    sys.modules["phoenix"] = fake_phoenix

import main
from kuro_backend.enterprise_ops.deployment_profiles import DEPLOYMENT_PROFILES, STABLE_RUNTIME_FLAGS
from kuro_backend.enterprise_ops.startup_validation import (
    log_startup_validation,
    validate_startup_environment,
)


def test_env_example_contains_required_keys():
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    required_keys = [
        "KURO_DEPLOYMENT_PROFILE",
        "JWT_SECRET_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "TELEGRAM_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_WEBHOOK_SECRET",
        "SERPER_API_KEY",
        "OPENCLAW_BASE_URL",
        "OPENCLAW_API_KEY",
        "KURO_FINANCE_DB_PATH",
        "KURO_MARKET_V2_DB_PATH",
        "KURO_ENTERPRISE_OBSERVABILITY_DB_PATH",
        "KURO_BACKUP_ENABLED",
        "KURO_BACKUP_DIR",
        "KURO_MODEL_GEMINI_FAST",
        "KURO_API_V2_ENABLED",
    ]

    for key in required_keys:
        assert f"{key}=" in env_example
    assert "sk-" not in env_example
    assert "Bearer " not in env_example


def test_production_env_example_uses_stable_flags_without_secrets():
    env_text = (PROJECT_ROOT / ".env.production.example").read_text(encoding="utf-8")

    required_keys = [
        "KURO_DEPLOYMENT_PROFILE",
        "JWT_SECRET_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "TELEGRAM_TOKEN",
        "TELEGRAM_CHAT_ID",
        "OPENCLAW_ENABLED",
        "KURO_BACKUP_ENABLED",
    ]
    for key in required_keys:
        assert f"{key}=" in env_text

    for flag, enabled in STABLE_RUNTIME_FLAGS.items():
        expected = "true" if enabled else "false"
        assert f"{flag}={expected}" in env_text

    assert "KURO_DEV_MODE=false" in env_text
    assert "OPENCLAW_ENABLED=false" in env_text
    assert "sk-" not in env_text
    assert "Bearer " not in env_text
    assert "dummy-" not in env_text


def test_deployment_profiles_exist():
    assert set(DEPLOYMENT_PROFILES) == {
        "local-dev",
        "single-vm",
        "docker-compose",
        "staging",
        "enterprise-pilot",
    }
    assert DEPLOYMENT_PROFILES["enterprise-pilot"].recommended_flags["KURO_BACKUP_ENABLED"] is True


def test_stable_profiles_recommend_completed_runtime_flags():
    for profile_id in ("single-vm", "staging", "enterprise-pilot"):
        flags = DEPLOYMENT_PROFILES[profile_id].recommended_flags
        for flag, enabled in STABLE_RUNTIME_FLAGS.items():
            assert flags[flag] is enabled


def test_local_dev_profile_remains_conservative():
    flags = DEPLOYMENT_PROFILES["local-dev"].recommended_flags

    assert flags["KURO_API_V2_ENABLED"] is False
    assert flags["KURO_ENTERPRISE_OBSERVABILITY_ENABLED"] is False
    assert "KURO_MEMORY_V3_ENABLED" not in flags
    assert "KURO_DEV_MODE" not in flags


def test_startup_validation_masks_secrets():
    stream = io.StringIO()
    logger = logging.getLogger("test_startup_validation_masks_secrets")
    logger.handlers = []
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    environ = {
        "KURO_DEPLOYMENT_PROFILE": "local-dev",
        "JWT_SECRET_KEY": "dummy-jwt-value-for-test",
        "GEMINI_API_KEY": "dummy-gemini-key-for-test",
        "TELEGRAM_TOKEN": "dummy-telegram-token-for-test",
    }

    result = validate_startup_environment(environ=environ)
    log_startup_validation(result, logger)
    output = stream.getvalue()

    assert "GEMINI_API_KEY" in output
    assert "TELEGRAM_TOKEN" in output
    assert "dummy-gemini-key-for-test" not in output
    assert "dummy-telegram-token-for-test" not in output
    assert "dummy-jwt-value-for-test" not in output


def test_health_endpoints_are_public_safe(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "dummy-health-auth-value")
    client = TestClient(main.app)

    for route in ("/api/live", "/api/ready", "/api/health"):
        response = client.get(route)
        assert response.status_code in {200, 503}
        body = response.json()
        serialized = json.dumps(body, sort_keys=True).lower()
        assert body["data"]["service"] == "kuro-ai"
        assert "dummy-health-auth-value" not in serialized
        assert "api_key" not in serialized
        assert "password" not in serialized
        assert "memory_stats" not in serialized
        assert "db_path" not in serialized
        assert "/home/" not in serialized


def test_backup_and_deployment_docs_exist():
    deployment_docs = [
        "local_dev.md",
        "single_vm.md",
        "docker_compose.md",
        "staging.md",
        "enterprise_pilot.md",
        "secrets.md",
        "backup_restore.md",
        "monitoring.md",
        "incident_response.md",
    ]
    for doc in deployment_docs:
        path = PROJECT_ROOT / "docs" / "deployment" / doc
        assert path.exists(), doc
        assert path.read_text(encoding="utf-8").strip()
    assert (PROJECT_ROOT / "docs" / "enterprise_refactor" / "14_deployment_ops.md").exists()


def test_docker_compose_has_no_real_secrets():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "services:" in compose
    assert "app:" in compose
    assert "phoenix:" in compose
    assert "sk-" not in compose
    assert "Bearer " not in compose
