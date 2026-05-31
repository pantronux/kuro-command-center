from __future__ import annotations

from pathlib import Path

from kuro_backend.krc_advisor import KRC_PERSONA_ID, PHD_ADVISOR_SYSTEM_PROMPT


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_krc_persona_id_is_phd_advisor():
    assert KRC_PERSONA_ID == "phd_advisor"


def test_krc_shell_uses_phd_advisor_copy():
    html = (PROJECT_ROOT / "web_interface/templates/krc_shell.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "web_interface/static/js/krc_shell.js").read_text(encoding="utf-8")

    assert "PhD Advisor" in html
    assert "phd_advisor" in js
    assert "data-persona=\"consultant\"" not in html
    assert "Persona:" not in html


def test_prompt_disallows_real_person_impersonation():
    assert "not a real person" in PHD_ADVISOR_SYSTEM_PROMPT
    assert "must not claim to be one" in PHD_ADVISOR_SYSTEM_PROMPT
    assert "I am Thomas" not in PHD_ADVISOR_SYSTEM_PROMPT
