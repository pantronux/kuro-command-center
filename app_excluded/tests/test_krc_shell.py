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


KRC_TEMPLATE = PROJECT_ROOT / "web_interface" / "templates" / "krc_shell.html"
KRC_CSS = PROJECT_ROOT / "web_interface" / "static" / "css" / "krc_shell.css"
KRC_JS = PROJECT_ROOT / "web_interface" / "static" / "js" / "krc_shell.js"
INDEX_TEMPLATE = PROJECT_ROOT / "web_interface" / "templates" / "index.html"


def _client_as(
    monkeypatch,
    username: str = "Pantronux",
    role: str = "Administrator",
) -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    monkeypatch.setattr(
        main.auth_db,
        "get_user",
        lambda _username: {
            "display_name": username,
            "role": role,
            "master_name": f"Master {username}",
            "restricted_persona": "",
        },
    )
    return TestClient(main.app)


def _get_shell(client: TestClient):
    return client.get("/krc-shell", cookies={main.COOKIE_NAME: "Bearer dummy"})


def test_krc_shell_route_disabled_by_default(monkeypatch):
    monkeypatch.delenv("KURO_KRC_SHELL_ENABLED", raising=False)

    client = TestClient(main.app)
    response = client.get("/krc-shell")

    assert response.status_code == 404


def test_krc_shell_route_enabled_for_admin(monkeypatch):
    monkeypatch.setenv("KURO_KRC_SHELL_ENABLED", "true")
    monkeypatch.setenv("ADMIN_USERNAME", "Pantronux")
    monkeypatch.delenv("KURO_DEV_MODE", raising=False)
    monkeypatch.setenv("KURO_APP_PROFILE", "legacy")

    client = _client_as(monkeypatch, username="Pantronux", role="Administrator")
    response = _get_shell(client)

    assert response.status_code == 200
    html = response.text
    assert 'data-krc-shell-route="/krc-shell"' in html
    assert "Kuro Research Center" in html
    assert "Administration Settings" in html
    assert 'data-prototype-marker="admin-settings-modal"' in html
    assert "qa_playground_enabled" not in html
    assert "qa_productization_enabled" not in html


def test_krc_shell_route_rejects_non_admin_without_dev_access(monkeypatch):
    monkeypatch.setenv("KURO_KRC_SHELL_ENABLED", "true")
    monkeypatch.setenv("ADMIN_USERNAME", "Pantronux")
    monkeypatch.setenv("KURO_APP_PROFILE", "legacy")
    monkeypatch.setenv("KURO_DEV_MODE", "false")

    client = _client_as(monkeypatch, username="Faikhira", role="User")
    response = _get_shell(client)

    assert response.status_code == 403


def test_krc_shell_route_allows_dev_profile_without_admin_controls(monkeypatch):
    monkeypatch.setenv("KURO_KRC_SHELL_ENABLED", "true")
    monkeypatch.setenv("ADMIN_USERNAME", "Pantronux")
    monkeypatch.setenv("KURO_APP_PROFILE", "dev")
    monkeypatch.delenv("KURO_DEV_MODE", raising=False)

    client = _client_as(monkeypatch, username="Faikhira", role="Developer")
    response = _get_shell(client)

    assert response.status_code == 200
    html = response.text
    assert 'data-krc-shell-admin="false"' in html
    assert "Kuro Research Center" in html
    assert "Administration Settings" not in html
    assert 'data-prototype-marker="admin-settings-modal"' not in html
    assert 'data-admin-only="true"' not in html


def test_krc_shell_template_is_official_research_shell():
    html = KRC_TEMPLATE.read_text(encoding="utf-8")
    css = KRC_CSS.read_text(encoding="utf-8")
    js = KRC_JS.read_text(encoding="utf-8")

    assert 'data-krc-shell="official-research"' in html
    assert 'data-prototype-source="Kuro-UI-Prototype"' not in html
    assert 'data-prototype-marker="sidebar-session-playground"' in html
    assert 'data-prototype-marker="prototype-header"' in html
    assert 'data-prototype-marker="research-console-playground-first"' in html
    assert 'data-prototype-marker="prototype-composer"' in html
    assert 'data-prototype-marker="profile-menu"' in html
    assert 'data-prototype-marker="playground-runtime-view"' in html
    assert 'data-prototype-marker="playground-runtime-drawer"' in html
    assert 'data-prototype-marker="admin-settings-modal"' in html
    assert 'data-prototype-marker="kuro-playground-card"' not in html
    assert "PhD Research Workspace" in html
    assert "PhD Advisor" in html
    assert "Literature Library" in html
    assert "Research Questions" in html
    assert "Novelty Gap Board" in html
    assert "Argument Map" in html
    assert "Kuro Playground" not in html
    assert "Playground Runtime" in html
    assert "Session History" in html
    assert "Forensic Integrity Overview" in html
    assert "Analyze in KS" in html
    assert 'data-prototype-marker="playground-artifact-trust-drawer"' in html
    assert "Research Console" in html
    assert "/static/css/krc_shell.css" in html
    assert "/static/js/krc_shell.js" in html

    assert "--krc-bg: #1a1a1f" in css
    assert "--krc-bg-sidebar: #18181d" in css
    assert "--krc-primary: #14b8a6" in css
    assert ".krc-sidebar" in css
    assert ".krc-composer" in css
    assert ".krc-drawer" in css

    for endpoint in [
        "/api/chats",
        "/api/chat/stream",
        "/api/models",
        "/api/capabilities",
        "/api/tools",
        "/api/runtimes",
        "/api/system-status",
        "/api/playground/sessions",
        "/api/playground/executions",
        "/api/playground/comparative-executions",
        "/api/playground/health",
        "/api/playground/providers",
        "/api/integrations/kuro-stack/analyze-playground",
    ]:
        assert endpoint in js

    removed_qa_shell_fragments = [
        "QA Playground",
        "krcQA",
        "data-krc-view-target=\"qa\"",
        "data-krc-qa-action",
        "/api/playground/qa/",
        "Generate Testcases",
        "Generate Gherkin",
    ]
    for fragment in removed_qa_shell_fragments:
        assert fragment not in html
        assert fragment not in js

    destructive_fragments = [
        "/api/backup/run",
        "/api/ingestion/chroma/cleanup-orphans",
        "/api/ingestion/datasets/${",
        "delete(",
        "method: \"DELETE\"",
        "method: 'DELETE'",
    ]
    for fragment in destructive_fragments:
        assert fragment not in js


def test_index_html_still_exists_and_is_not_replaced():
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")
    main_py = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")

    assert INDEX_TEMPLATE.exists()
    assert KRC_TEMPLATE.exists()
    assert "Kuro AI - Web Dashboard" in html
    assert "/static/css/krc_shell.css" not in html
    assert "/static/js/krc_shell.js" not in html
    assert 'return "index.html"' in main_py
    assert '@app.get("/krc-shell"' in main_py
