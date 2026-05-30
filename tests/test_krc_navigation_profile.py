from __future__ import annotations

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


def _dashboard(monkeypatch, username: str = "Pantronux", role: str = "Administrator"):
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    monkeypatch.setattr(
        main.auth_db,
        "get_user",
        lambda _username: {
            "display_name": username,
            "role": role,
            "master_name": f"Master {username}",
        },
    )
    client = TestClient(main.app)
    return client.get("/", cookies={main.COOKIE_NAME: "Bearer dummy"})


def test_legacy_navigation_render_stays_unchanged(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "legacy")

    response = _dashboard(monkeypatch)

    assert response.status_code == 200
    html = response.text
    assert 'data-app-profile="legacy"' in html
    assert "Kuro AI" in html
    assert "New Chat" in html
    assert "data-krc-persona-locked" not in html
    assert 'data-persona="consultant"' in html
    assert 'data-persona="advisor"' in html
    assert 'href="/market"' in html
    assert "Market Sentinel" in html
    assert "Telegram" in html
    assert "krcWorkspaceNav" not in html


def test_krc_navigation_render_is_playground_first(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    monkeypatch.delenv("KURO_KRC_MARKET_ENABLED", raising=False)
    monkeypatch.delenv("KURO_KRC_TELEGRAM_CENTER_ENABLED", raising=False)

    response = _dashboard(monkeypatch)

    assert response.status_code == 200
    html = response.text
    assert 'data-app-profile="krc"' in html
    assert "Kuro Research Center" in html
    assert "New Research Console" in html
    assert "id=\"krcWorkspaceNav\"" in html
    assert "Research Playground" in html
    assert "Kuro Playground" in html
    assert "Kuro Playground Runtime" not in html
    assert "Workspace runtime for research prompts" not in html
    assert 'data-krc-persona-locked="true"' in html
    assert "Persona:" in html
    assert "Advisor" in html
    assert 'data-persona="consultant"' not in html
    assert 'data-persona="tactical"' not in html
    assert 'data-persona="advisor"' not in html
    assert "QA Playground" not in html
    assert "id=\"qaRequirementInput\"" not in html
    assert "id=\"krcNavEvaluation\"" not in html
    assert "Evaluation Summary" not in html
    assert "id=\"krcPlaygroundLanding\"" in html
    assert html.index("id=\"krcPlaygroundLanding\"") < html.index("class=\"pg-grid")
    assert html.index("class=\"pg-grid") < html.index("id=\"playgroundOutput\"")
    assert html.index("id=\"krcPlaygroundLanding\"") < html.index('href="/playground/tutorial"')
    assert "id=\"krcLandingResearchBtn\"" not in html
    assert 'href="/market"' not in html
    assert "data-admin-settings-tab=\"telegram\"" in html
    assert "data-krc-feature=\"telegram_center\"" in html


def test_krc_optional_qa_and_evaluation_can_be_revealed_by_flags(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    monkeypatch.setenv("KURO_KRC_QA_PLAYGROUND_ENABLED", "true")
    monkeypatch.setenv("KURO_KRC_EVALUATION_ENABLED", "true")

    response = _dashboard(monkeypatch)

    assert response.status_code == 200
    html = response.text
    assert "QA Playground" in html
    assert "id=\"qaRequirementInput\"" in html
    assert "id=\"krcNavEvaluation\"" in html
    assert "data-admin-settings-tab=\"evaluation\"" in html


def test_krc_non_admin_does_not_render_admin_controls(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")

    response = _dashboard(monkeypatch, username="Faikhira", role="User")

    assert response.status_code == 200
    html = response.text
    assert "Kuro Research Center" in html
    assert "Administration Settings" not in html
    assert "id=\"krcNavIngestion\"" not in html
    assert "id=\"krcNavEvaluation\"" not in html


def test_dashboard_template_has_legacy_krc_profile_fallback(monkeypatch):
    monkeypatch.delenv("KURO_APP_PROFILE", raising=False)

    template = main.templates.get_template("index.html")
    html = template.render(
        {
            "username": "Pantronux",
            "display_name": "Pantronux",
            "role": "Administrator",
            "is_admin": True,
            "restricted_persona": "",
            "master_name": "Master Pantronux",
            "custom_persona": "",
        }
    )

    assert "Kuro AI - Web Dashboard" in html
    assert 'data-app-profile="legacy"' in html
