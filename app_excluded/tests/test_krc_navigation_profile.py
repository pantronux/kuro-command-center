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


def _client(monkeypatch, username: str = "Pantronux", role: str = "Administrator"):
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
    return TestClient(main.app)


def _dashboard(monkeypatch, username: str = "Pantronux", role: str = "Administrator"):
    client = _client(monkeypatch, username=username, role=role)
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


def test_krc_root_redirects_to_research_shell(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")

    client = _client(monkeypatch)
    response = client.get(
        "/",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/research"


def test_research_shell_is_phd_research_first(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")

    client = _client(monkeypatch)
    response = client.get("/research", cookies={main.COOKIE_NAME: "Bearer dummy"})

    assert response.status_code == 200
    html = response.text
    assert "Kuro Research Center" in html
    assert "New Research Console" in html
    assert "PhD Advisor" in html
    assert "Literature Library" in html
    assert "Research Questions" in html
    assert "Novelty Gap Board" in html
    assert "Argument Map" in html
    assert "QA Playground" not in html
    assert 'href="/market"' not in html
    assert "Legacy Chat" not in html


def test_krc_optional_qa_and_evaluation_can_be_revealed_by_flags(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    monkeypatch.setenv("KURO_KRC_QA_PLAYGROUND_ENABLED", "true")
    monkeypatch.setenv("KURO_KRC_EVALUATION_ENABLED", "true")

    response = _client(monkeypatch).get("/api/capabilities")

    assert response.status_code == 200
    krc = response.json()["data"]["krc"]
    assert krc["features"]["qa_playground"] is True
    assert krc["features"]["evaluation"] is True


def test_krc_non_admin_does_not_render_admin_controls(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")

    response = _dashboard(monkeypatch, username="Faikhira", role="User")

    assert response.status_code == 200
    assert "Kuro Research Center" in response.text
    assert "Administration Settings" not in response.text


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
