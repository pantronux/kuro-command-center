"""Tests for Kuro AI V6.1 Sovereign UI mode router (primarily EN, legacy BI retained).

--- Header Doc ---
Purpose: Verify keyword detection for UI mode switching (HUD/RESEARCH/CINEMA).
Covers: kuro_backend.ui_mode_router.detect_mode_command.
Fixtures: None (pure regex).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *a, **kw):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

if "phoenix" not in sys.modules:
    fake_phoenix = types.ModuleType("phoenix")
    fake_phoenix.launch_app = lambda *a, **k: types.SimpleNamespace(
        url="http://x", close=lambda: None,
    )
    sys.modules["phoenix"] = fake_phoenix

from kuro_backend import ui_mode_router  # noqa: E402


@pytest.mark.parametrize(
    "text,expected_cmd",
    [
        # V6.1 Sebastian-register English triggers
        ("Kuro, activate research mode", "RESEARCH_MODE"),
        ("Kuro, enter research mode please", "RESEARCH_MODE"),
        ("engage research mode", "RESEARCH_MODE"),
        ("Kuro, switch to hud", "HUD_MODE"),
        ("activate hud mode", "HUD_MODE"),
        ("engage HUD please", "HUD_MODE"),
        ("switch to cinema mode", "CINEMA_MODE"),
        ("activate cinema mode", "CINEMA_MODE"),
        ("stand down", "NORMAL_MODE"),
        ("resume normal mode", "NORMAL_MODE"),
        ("return to normal", "NORMAL_MODE"),
        ("Kuro, system status", "STATUS_TICKER"),
        ("status report please", "STATUS_TICKER"),
        # Legacy Bahasa triggers must keep working
        ("Kuro, mode riset", "RESEARCH_MODE"),
        ("Kuro, research mode please", "RESEARCH_MODE"),
        ("aktifkan mode peneliti", "RESEARCH_MODE"),
        ("Kuro, hud mode", "HUD_MODE"),
        ("jarvis mode!", "HUD_MODE"),
        ("nyalakan mode jarvis", "HUD_MODE"),
        ("mode cinema tolong", "CINEMA_MODE"),
        ("Kuro, cinema mode", "CINEMA_MODE"),
        ("mode bioskop", "CINEMA_MODE"),
        ("mode normal", "NORMAL_MODE"),
        ("kembali normal saja", "NORMAL_MODE"),
    ],
)
def test_detect_mode_command_matches_known_phrases(text, expected_cmd):
    result = ui_mode_router.detect_mode_command(text)
    assert result is not None, f"expected match for {text!r}"
    cmd, _ = result
    assert cmd == expected_cmd


def test_detect_mode_command_returns_cleaned_remainder():
    result = ui_mode_router.detect_mode_command(
        "Kuro, mode riset dan ringkas status server"
    )
    assert result is not None
    cmd, cleaned = result
    assert cmd == "RESEARCH_MODE"
    assert "ringkas status server" in cleaned
    assert "mode riset" not in cleaned.lower()


def test_detect_mode_command_no_match_returns_none():
    assert ui_mode_router.detect_mode_command("cerita tentang kucing") is None
    assert ui_mode_router.detect_mode_command("") is None
    assert ui_mode_router.detect_mode_command(None) is None  # type: ignore[arg-type]


def test_normal_mode_wins_when_exit_phrase_present():
    result = ui_mode_router.detect_mode_command("Kuro, keluar dari HUD mode")
    assert result is not None
    cmd, cleaned = result
    assert cmd == "NORMAL_MODE"
    assert "HUD" not in cleaned


def test_acknowledgement_for_each_mode_is_non_empty():
    for cmd in ("HUD_MODE", "RESEARCH_MODE", "CINEMA_MODE", "NORMAL_MODE", "STATUS_TICKER"):
        ack = ui_mode_router.acknowledgement(cmd)
        assert isinstance(ack, str) and len(ack) > 10


def test_acknowledgement_fallback_for_unknown_command():
    ack = ui_mode_router.acknowledgement("UNKNOWN_CMD")
    assert "UI command acknowledged" in ack


def test_acknowledgements_are_in_english():
    """V6.1 — every ACK must read as Sebastian-register English."""
    for cmd in ("HUD_MODE", "RESEARCH_MODE", "CINEMA_MODE", "NORMAL_MODE", "STATUS_TICKER"):
        ack = ui_mode_router.acknowledgement(cmd)
        assert "Master" in ack
        assert "Baik Master" not in ack
        assert "Siap Master" not in ack
        assert "sudah saya kirim" not in ack


def test_address_prefix_is_stripped():
    result = ui_mode_router.detect_mode_command("hey kuro: mode hud")
    assert result is not None
    cmd, _ = result
    assert cmd == "HUD_MODE"
