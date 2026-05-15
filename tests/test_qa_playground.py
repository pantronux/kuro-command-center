"""QA playground runtime tests for Prompt 6."""

from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

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


def _auth_client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_qa_testcase_generation_returns_valid_schema(monkeypatch):
    from kuro_backend.provider.provider_interface import ProviderResponse

    parser_payload = (
        '{"main_functionality":"User login","acceptance_criteria":["email+password"],'
        '"constraints":[],"edge_cases":[],"raw_requirement":"User login"}'
    )
    testcase_payload = (
        '{"test_cases":[{"id":"TC-001","title":"Login berhasil","precondition":"Akun aktif",'
        '"steps":[{"step_number":1,"action":"Input email/password","expected_result":"Data diterima"}],'
        '"expected_result":"Masuk dashboard","priority":"high","type":"functional"}]}'
    )

    with patch("kuro_backend.playground.qa.requirement_parser.ProviderRouter") as parser_router, patch(
        "kuro_backend.playground.qa.testcase_generator.ProviderRouter"
    ) as testcase_router:
        parser_router.return_value.route = AsyncMock(
            return_value=ProviderResponse(
                provider="gemini",
                model="test",
                content=parser_payload,
            )
        )
        testcase_router.return_value.route = AsyncMock(
            return_value=ProviderResponse(
                provider="gemini",
                model="test",
                content=testcase_payload,
            )
        )
        client = _auth_client(monkeypatch)
        resp = client.post(
            "/api/playground/qa/generate-testcases",
            json={"requirement": "User can login with email and password"},
            cookies={main.COOKIE_NAME: "Bearer dummy"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("schema_version") == "qa_output_v1"
    assert isinstance(data.get("test_cases"), list)
    assert len(data.get("test_cases")) >= 1


def test_qa_gherkin_contains_scenario_keyword(monkeypatch):
    from kuro_backend.provider.provider_interface import ProviderResponse

    parser_payload = (
        '{"main_functionality":"Reset password","acceptance_criteria":[],"constraints":[],'
        '"edge_cases":[],"raw_requirement":"Reset password"}'
    )
    gherkin_payload = (
        "Feature: Password Reset\n"
        "Scenario: User resets password\n"
        "Given user opens forgot password page\n"
        "When user submits registered email\n"
        "Then reset link is sent"
    )

    with patch("kuro_backend.playground.qa.requirement_parser.ProviderRouter") as parser_router, patch(
        "kuro_backend.playground.qa.cucumber_generator.ProviderRouter"
    ) as gherkin_router:
        parser_router.return_value.route = AsyncMock(
            return_value=ProviderResponse(provider="gemini", model="test", content=parser_payload)
        )
        gherkin_router.return_value.route = AsyncMock(
            return_value=ProviderResponse(provider="gemini", model="test", content=gherkin_payload)
        )
        client = _auth_client(monkeypatch)
        resp = client.post(
            "/api/playground/qa/generate-gherkin",
            json={"requirement": "User can reset password"},
            cookies={main.COOKIE_NAME: "Bearer dummy"},
        )

    assert resp.status_code == 200
    assert "Scenario" in resp.json().get("gherkin", "")


def test_qa_boundary_memory_isolation(monkeypatch):
    monkeypatch.setenv("KURO_V2_STRICT_MODE", "true")
    from kuro_backend.playground.qa.qa_runtime import QARuntime
    from kuro_backend.runtime.boundary_guard import BoundaryViolationError

    runtime = QARuntime(username="testuser", chat_id="chat_001")
    with patch(
        "kuro_backend.playground.qa.qa_runtime.assert_memory_access",
        side_effect=BoundaryViolationError("blocked"),
    ):
        result = asyncio.run(runtime.process_request("generate_testcases", "simple req"))
    assert isinstance(result, dict)
    assert "ok" in result


def test_qa_disabled_returns_503(monkeypatch):
    monkeypatch.setenv("KURO_QA_PLAYGROUND_ENABLED", "false")
    client = _auth_client(monkeypatch)
    resp = client.post(
        "/api/playground/qa/generate-testcases",
        json={"requirement": "test"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 503


def test_requirement_parser_returns_safe_default_on_llm_failure(monkeypatch):
    from kuro_backend.playground.qa.requirement_parser import parse_requirements
    from kuro_backend.runtime.runtime_context import resolve_runtime_context

    ctx = resolve_runtime_context("qa", username="testuser")
    with patch("kuro_backend.playground.qa.requirement_parser.ProviderRouter") as mock_router:
        mock_router.return_value.route = AsyncMock(side_effect=RuntimeError("LLM failed"))
        result = asyncio.run(parse_requirements("some req", ctx))
    assert isinstance(result, dict)
    assert "main_functionality" in result
