"""Kuro V6.1 — branding + Live2D template smoke tests.

These tests don't spin up the FastAPI app; they just assert the dashboard
HTML templates ship the new favicon links, the real avatar image, the
Live2D canvas dock, and the loader <script type="module"> entry point.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEMPLATES = PROJECT_ROOT / "web_interface" / "templates"


def _read(name: str) -> str:
    path = TEMPLATES / name
    assert path.exists(), f"missing template: {path}"
    return path.read_text(encoding="utf-8")


def test_index_wires_favicon_and_avatar():
    html = _read("index.html")
    assert 'href="/profile/favicon.ico"' in html
    assert "/profile/kuro_avatar.png" in html


def test_index_has_live2d_canvas_and_loader():
    html = _read("index.html")
    assert '<canvas id="live2d-canvas"' in html
    assert 'id="live2dDock"' in html
    assert "/static/js/live2d_manager.js" in html


def test_secondary_templates_have_favicon():
    for name in ("reminder.html", "daily_habits.html", "intelligence.html",
                 "login.html", "compliance.html"):
        html = _read(name)
        assert '/profile/favicon.ico' in html, f"{name} missing favicon link"


def test_live2d_manager_source_exists_and_exports_api():
    manager = PROJECT_ROOT / "web_interface" / "static" / "js" / "live2d_manager.js"
    assert manager.exists(), "live2d_manager.js missing"
    src = manager.read_text(encoding="utf-8")
    for symbol in ("initLive2D", "setLipSyncValue", "playTalkMotion", "returnToIdle"):
        assert symbol in src, f"live2d_manager.js must export {symbol}"
    assert "/profile/live2d/hijiki/runtime/hijiki.model3.json" in src


def test_vendor_readme_documents_offline_fallback():
    readme = PROJECT_ROOT / "web_interface" / "static" / "vendor" / "live2d" / "README.md"
    assert readme.exists(), "vendor live2d README.md missing"
    body = readme.read_text(encoding="utf-8")
    assert "live2dcubismcore.min.js" in body
    assert "pixi-live2d-display" in body
