"""Per-persona Piper tuning (Chancellor sterner register).

--- Header Doc ---
Purpose: Lock per-persona voice tuning (length scale / pitch) table.
Covers: kuro_backend.voice_profiles.VOICE_PROFILES + get_profile.
Fixtures: None.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_chancellor_voice_profile_is_stern():
    from kuro_backend import voice_profiles

    p = voice_profiles.for_persona("chancellor")
    assert p.length_scale == 1.0
    assert p.pitch_shift == pytest.approx(0.9)


def test_unknown_persona_falls_back_to_env_defaults():
    from kuro_backend import voice_profiles

    p = voice_profiles.for_persona("not-a-real-persona")
    assert p.length_scale is None
    assert p.pitch_shift is None
