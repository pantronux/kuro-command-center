from __future__ import annotations

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


def _provider_response(content: str):
    from kuro_backend.provider.provider_interface import ProviderResponse

    return ProviderResponse(provider="gemini", model="test", content=content)


def test_krc_qa_productization_routes_return_structured_outputs(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    monkeypatch.setenv("KURO_KRC_QA_PLAYGROUND_ENABLED", "true")
    monkeypatch.setenv("KURO_KRC_QA_PRODUCTIZATION_ENABLED", "true")
    monkeypatch.delenv("KURO_QA_PLAYGROUND_ENABLED", raising=False)

    parser_payload = (
        '{"main_functionality":"User exports QA coverage","acceptance_criteria":'
        '["Export includes generated test cases"],"constraints":["JSON export"],'
        '"edge_cases":["No test cases generated"],"raw_requirement":"User exports QA coverage"}'
    )
    testcase_payload = (
        '{"test_cases":[{"id":"TC-001","title":"Export includes generated test cases",'
        '"precondition":"QA requirement exists","steps":[{"step_number":1,'
        '"action":"Generate export","expected_result":"JSON contains test_cases"}],'
        '"expected_result":"Bundle is returned","priority":"high","type":"functional"}]}'
    )
    gherkin_payload = "Feature: QA Export\nScenario: Export bundle is prepared"

    with patch("kuro_backend.playground.qa.requirement_parser.ProviderRouter") as parser_router, patch(
        "kuro_backend.playground.qa.testcase_generator.ProviderRouter"
    ) as testcase_router, patch(
        "kuro_backend.playground.qa.cucumber_generator.ProviderRouter"
    ) as gherkin_router:
        parser_router.return_value.route = AsyncMock(
            return_value=_provider_response(parser_payload)
        )
        testcase_router.return_value.route = AsyncMock(
            return_value=_provider_response(testcase_payload)
        )
        gherkin_router.return_value.route = AsyncMock(
            return_value=_provider_response(gherkin_payload)
        )

        client = _auth_client(monkeypatch)
        cookies = {main.COOKIE_NAME: "Bearer dummy"}
        ambiguity = client.post(
            "/api/playground/qa/analyze-ambiguity",
            json={"requirement": "User exports QA coverage as JSON."},
            cookies=cookies,
        )
        coverage = client.post(
            "/api/playground/qa/coverage-matrix",
            json={"requirement": "User exports QA coverage as JSON."},
            cookies=cookies,
        )
        export = client.post(
            "/api/playground/qa/export",
            json={"requirement": "User exports QA coverage as JSON.", "format": "json"},
            cookies=cookies,
        )

    assert ambiguity.status_code == 200
    assert ambiguity.json()["schema_version"] == "qa_productization_v1"
    assert ambiguity.json()["task_type"] == "ambiguity_analysis"
    assert "trace_id" in ambiguity.json()

    assert coverage.status_code == 200
    coverage_body = coverage.json()
    assert coverage_body["task_type"] == "coverage_matrix"
    assert coverage_body["requirements"][0]["coverage"] == "covered"

    assert export.status_code == 200
    export_body = export.json()
    assert export_body["schema_version"] == "qa_export_plan_v1"
    assert export_body["export_status"] == "prepared"
    assert "artifact" in export_body


def test_krc_qa_productization_routes_disabled_outside_krc(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "legacy")
    client = _auth_client(monkeypatch)

    response = client.post(
        "/api/playground/qa/analyze-ambiguity",
        json={"requirement": "Legacy mode should keep new KRC QA track off."},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 503
    assert "QA productization track disabled" in response.text


def test_krc_qa_playground_flag_disables_existing_qa_routes(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    monkeypatch.setenv("KURO_KRC_QA_PLAYGROUND_ENABLED", "false")
    monkeypatch.delenv("KURO_QA_PLAYGROUND_ENABLED", raising=False)
    client = _auth_client(monkeypatch)

    response = client.post(
        "/api/playground/qa/interpret",
        json={"requirement": "Disabled KRC QA route"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 503


def test_krc_qa_routes_are_disabled_by_default(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    monkeypatch.delenv("KURO_KRC_QA_PLAYGROUND_ENABLED", raising=False)
    monkeypatch.delenv("KURO_KRC_QA_PRODUCTIZATION_ENABLED", raising=False)
    monkeypatch.delenv("KURO_QA_PLAYGROUND_ENABLED", raising=False)
    client = _auth_client(monkeypatch)

    interpret = client.post(
        "/api/playground/qa/interpret",
        json={"requirement": "Default KRC research mode should hide QA."},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    product = client.post(
        "/api/playground/qa/analyze-ambiguity",
        json={"requirement": "Default KRC research mode should hide QA."},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert interpret.status_code == 503
    assert product.status_code == 503
