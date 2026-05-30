from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "web_interface" / "templates" / "index.html"
STYLE = ROOT / "web_interface" / "static" / "css" / "style.css"
REVAMP_STYLE = ROOT / "web_interface" / "static" / "css" / "index_revamp.css"
APP_JS = ROOT / "web_interface" / "static" / "js" / "app.js"
MAIN = ROOT / "main.py"


def test_v1_dashboard_uses_dark_gray_redesign_shell():
    html = INDEX.read_text(encoding="utf-8")
    css = STYLE.read_text(encoding="utf-8")
    revamp_css = REVAMP_STYLE.read_text(encoding="utf-8")

    assert 'class="kuro-redesign-v1' in html
    assert "/static/css/index_revamp.css" in html
    assert "index_revamp.css?v=20260525-01" in html
    assert "id=\"composerActionMenu\"" in html
    assert "id=\"minimizeSidebar\"" in html
    assert "sidebar-collapse-toggle" in html
    assert "title=\"Hide sidebar\"" in html
    assert "profile-menu-trigger" in html
    assert "<span>K</span>" in html
    assert '<img src="/profile/kuro_avatar.png"' not in html

    assert "--kuro-bg-primary: #1a1a1a" in css
    assert "--kuro-bg-secondary: #212121" in css
    assert "--kuro-bg-tertiary: #2a2a2a" in css
    assert "--kuro-accent-primary: #0d9488" in css
    assert "--bg-primary: #1a1a1a" in revamp_css
    assert "body.kuro-redesign-v1 .hidden" in revamp_css
    assert "#welcomeScreen > div.welcome:first-child" in revamp_css
    assert '#sidebar.sidebar[data-collapsed="true"]' in revamp_css
    assert "Prototype skin pass" in revamp_css
    assert "--bg-primary: #1a1a1f" in revamp_css
    assert "sidebar-collapsed-shell" in revamp_css
    assert "--conversation-width: 900px" in revamp_css
    assert "#stopGeneratingBtn.hidden" in revamp_css
    assert "#chatContainer > .flex-row-reverse" in revamp_css
    assert "#minimizeSidebar.sidebar-collapse-toggle" in revamp_css
    assert '#sidebar.sidebar[data-collapsed="true"] #minimizeSidebar' in revamp_css
    assert "Show sidebar" in APP_JS.read_text(encoding="utf-8")


def test_v1_dashboard_is_the_only_frontend_shell():
    html = INDEX.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")

    assert not (ROOT / "web_interface" / "templates" / "index_v2.html").exists()
    assert not (ROOT / "web_interface" / "static" / "css" / "v2.css").exists()
    assert not (ROOT / "web_interface" / "static" / "js" / "v2").exists()
    assert not (ROOT / "web_interface" / "prototypes").exists()
    assert not (ROOT / "docs" / "ui_v2_reference").exists()
    assert 'return "index.html"' in main
    assert "KURO_FRONTEND_V2_ENABLED" not in main
    assert "index_v2" not in main
    assert "/static/css/v2.css" not in html


def test_v1_redesign_preserves_existing_playground_runtime_hooks():
    html = INDEX.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")

    assert "id=\"playgroundPanel\"" in html
    assert "id=\"playgroundSessionMode\"" in html
    assert "id=\"playgroundProviderChecklist\"" in html
    assert "id=\"playgroundIntegrityOverviewBtn\"" in html
    assert "id=\"playgroundKsAnalysisMode\"" in html
    assert "id=\"playgroundAnalyzeInKsBtn\"" in html
    assert "id=\"playgroundAnalyzeSessionInKsBtn\"" in html
    assert "async function playgroundCreateSession" in js
    assert "async function analyzePlaygroundInKuroStack" in js
    assert "buildKuroStackPlaygroundAnalysisPrompt" in js
    assert "fetchPlaygroundArtifactText" in js
    assert "'/api/integrations/kuro-stack/analyze-playground'" in js
    assert "resolvePlaygroundHandoffRequest" in js
    assert "'/api/playground/sessions'" in js
    assert "'/api/playground/executions'" in js
    assert "/api/playground/qa/interpret" in js
    assert "id=\"qaRequirementInput\"" in html


def test_v1_redesign_keeps_persona_and_existing_tool_navigation():
    html = INDEX.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")

    assert "id=\"personaAccordionBtn\"" in html
    assert "id=\"composerModelSelect\"" in html
    assert "id=\"welcomeModelSelect\"" in html
    assert "id=\"sidebarChatSearch\"" in html
    assert "id=\"sidebarSessionsMore\"" in html
    assert "id=\"chatSessionsList\"" in html
    assert "id=\"chatDrawer\"" not in html
    assert "kuro-profile-menu" in html
    assert "Administration Settings" in html
    assert "id=\"adminSettingsModal\"" in html
    assert "data-admin-settings-tab=\"memory-v3\"" in html
    assert "data-admin-settings-tab=\"provider-model\"" in html
    assert "data-admin-settings-tab=\"feature-flags\"" in html
    assert "Model Settings" in html
    assert "data-persona=\"consultant\"" in html
    assert "data-persona=\"auditor\"" in html
    assert "href=\"/intelligence\"" in html
    assert "href=\"/market\"" in html
    assert "href=\"/tutorial\"" in html
    assert "composerActionMenu" in js
    assert "elements.sendBtn?.classList.add('hidden')" in js
    assert "loadComposerModelAliases" in js
    assert "model_alias" in js
    assert "openFilesModal()" in js
    assert "navAdminSettings" in js
    assert "function openAdminSettings(" in js
    assert "'/api/admin/enterprise-flags'" in js
    assert "'/api/admin/providers/health'" in js
    assert "'/api/admin/memory-v3/health'" in js
    assert "'/api/ingestion/analytics/overview'" in js
    assert "function generateClientChatId()" in js
    assert "const isFirstTurnInNewChat = !currentChatId" in js
    assert "formData.append('chat_id', currentChatId)" in js
    assert "const requestChatId = currentChatId" in js
    assert "if (requestChatId !== currentChatId) return" in js
    assert "resetActiveConversationSurface({ showWelcome: true, focusWelcome: false })" in js


def test_v1_redesign_quiets_optional_proactive_reconnect_poll():
    js = APP_JS.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")

    assert "'/api/proactive-events?limit=5'" in js
    assert '@app.get("/api/proactive-events")' in main
