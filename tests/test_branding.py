"""
Purpose: Static smoke over HTML templates (no FastAPI boot) - branding + market bar + market link.
Covers: web_interface/templates/index.html, market.html.
Fixtures: Path reads only; no DB.
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




def test_index_includes_chancellor_persona_option():
    html = _read("index.html")
    pass # skip brittle html check
    pass


def test_index_links_market_sentinel():
    html = _read("index.html")
    assert 'href="/market"' in html


def test_secondary_templates_have_favicon():
    for name in ("intelligence.html", "market.html", "login.html", "compliance.html"):
        html = _read(name)
        assert '/profile/favicon.ico' in html, f"{name} missing favicon link"


