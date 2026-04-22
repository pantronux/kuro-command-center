"""Kuro V6.1 — smoke test that every persona prompt is English (Sebastian register).

This is a lightweight guardrail so a future regression that reintroduces
Bahasa Indonesia into the core system prompts trips immediately.

--- Header Doc ---
Purpose: Smoke lint — persona prompts are English + Chancellor SSoT addendum lists market tables.
Covers: kuro_backend.personas PERSONA_INSTRUCTIONS + _CHANCELLOR_SSOT_ADDENDUM.
Fixtures: None (pure string assertions).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kuro_backend import personas  # noqa: E402


BAHASA_FORBIDDEN = (
    "Kamu adalah",
    "Kamu memiliki",
    "Gunakan waktu",
    "DILARANG",
    "JANGAN",
    "WAJIB",
    "Anda wajib",
)


@pytest.mark.parametrize("key", list(personas.PERSONA_INSTRUCTIONS.keys()))
def test_persona_text_has_no_bahasa_remnants(key):
    text = personas.PERSONA_INSTRUCTIONS[key]
    for phrase in BAHASA_FORBIDDEN:
        assert phrase not in text, (
            f"persona {key!r} still contains Bahasa phrase {phrase!r}"
        )


def test_consultant_persona_is_butler_english():
    text = personas.PERSONA_INSTRUCTIONS["consultant"]
    assert "AI Butler" in text
    assert "Pantronux" in text
    assert "CORE KNOWLEDGE BASE" in text  # structural header preserved


def test_build_system_instruction_is_english_for_consultant():
    prompt = personas.build_system_instruction(
        "consultant",
        current_time="10:00",
        current_date="2026-04-17",
        kuro_version_label="V6.1",
        variant="graph",
    )
    for phrase in BAHASA_FORBIDDEN:
        assert phrase not in prompt, f"rendered prompt contains Bahasa: {phrase!r}"
    assert "CHAIN OF THOUGHT" in prompt
    assert "SSOT PRIORITY RULE" in prompt
    assert "HITL SECURITY POLICY" in prompt


def test_ssot_priority_directive_in_english():
    assert "SSOT PRIORITY RULE" in personas._SSOT_PRIORITY_DIRECTIVE
    assert "MANDATORY" in personas._SSOT_PRIORITY_DIRECTIVE
    for phrase in BAHASA_FORBIDDEN:
        assert phrase not in personas._SSOT_PRIORITY_DIRECTIVE


def test_chancellor_graph_prompt_includes_financial_ssot_addendum():
    prompt = personas.build_system_instruction(
        "chancellor",
        current_time="10:00",
        current_date="2026-04-17",
        kuro_version_label="V6.2",
        variant="graph",
    )
    assert "FINANCIAL SSoT PRIORITY" in prompt
    assert "api_usage_daily" in prompt
    assert "watched_symbols" in prompt
    for phrase in BAHASA_FORBIDDEN:
        assert phrase not in prompt, f"chancellor prompt contains Bahasa: {phrase!r}"
