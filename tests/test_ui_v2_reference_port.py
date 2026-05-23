from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "ui_v2_reference"
PROTO = ROOT / "web_interface" / "prototypes" / "ui_v2"
INDEX = ROOT / "web_interface" / "templates" / "index.html"
APP_JS = ROOT / "web_interface" / "static" / "js" / "app.js"
MAIN = ROOT / "main.py"
CONFIG = ROOT / "kuro_backend" / "config.py"
PROTOTYPE_SRC = ROOT / "Kuro-UI-Prototype-main" / "artifacts" / "kuro-ai" / "src"


REQUIRED_DOCS = [
    "README.md",
    "design_tokens.md",
    "screenshot_mapping.md",
    "component_mapping.md",
    "porting_plan.md",
    "deferred_wiring.md",
]

REQUIRED_REFERENCE = [
    "index_static.html",
    "v2_reference.css",
    "v2_reference.js",
    "README.md",
]

FORBIDDEN_SECRET_MARKERS = [
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "TELEGRAM_TOKEN",
    "SERPER_API_KEY",
    "sk-",
]


def test_reference_files_exist() -> None:
    for rel in REQUIRED_DOCS:
        assert (DOCS / rel).exists(), rel
    for rel in REQUIRED_REFERENCE:
        assert (PROTO / rel).exists(), rel


def test_production_ui_files_still_exist() -> None:
    assert INDEX.exists()
    assert APP_JS.exists()


def test_local_prototype_source_was_inspected() -> None:
    readme = (DOCS / "README.md").read_text(encoding="utf-8")
    assert "Kuro-UI-Prototype-main" in readme
    assert "Sidebar.tsx" in readme
    assert "Composer.tsx" in readme
    assert "Playground.tsx" in readme


def test_reference_html_contains_required_states() -> None:
    html = (PROTO / "index_static.html").read_text(encoding="utf-8")
    for marker in [
        "Kuro AI",
        "New Chat",
        "Administration Settings",
        "Deep Research",
        "Market Analysis",
        "Playground Runtime",
        "Chat Settings",
        "Reference only",
    ]:
        assert marker in html


def test_reference_files_do_not_contain_secret_markers_or_network_calls() -> None:
    combined = "\n".join(
        (PROTO / rel).read_text(encoding="utf-8")
        for rel in ["index_static.html", "v2_reference.css", "v2_reference.js"]
    )
    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in combined
    assert "fetch(" not in combined
    assert "XMLHttpRequest" not in combined
    assert "raw.githubusercontent.com" not in combined
    assert "api.github.com" not in combined


def test_production_index_not_replaced_by_static_reference() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "id=\"messageInput\"" in html
    assert "id=\"chatSessionsList\"" in html
    assert "id=\"personaAccordionBtn\"" in html
    assert "static mock from Kuro-UI-Prototype-main" not in html
    assert "./v2_reference.js" not in html


def test_frontend_v2_flag_not_enabled_by_default() -> None:
    text = MAIN.read_text(encoding="utf-8") + "\n" + CONFIG.read_text(encoding="utf-8")
    if "KURO_FRONTEND_V2_ENABLED" in text:
        assert "KURO_FRONTEND_V2_ENABLED\", \"false\"" in text or "KURO_FRONTEND_V2_ENABLED', 'false'" in text
    else:
        assert "index_v2" not in MAIN.read_text(encoding="utf-8")
