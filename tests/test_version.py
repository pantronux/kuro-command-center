"""Tests for Kuro AI V7.0 Leviathan version metadata.

Purpose: Lock version constants, banner, and `version_info()` payload shape.
Covers: kuro_backend.version.
Fixtures used: None (pure import + assert).
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_version_constants_match_v7_leviathan():
    from kuro_backend import version as v
    assert v.VERSION == "7.0.0"
    assert v.CODENAME == "Leviathan"
    assert v.VERSION_LABEL == "V7.0"
    assert "V7.0" in v.VERSION_BANNER
    assert "Leviathan" in v.VERSION_BANNER


def test_version_info_payload_shape():
    from kuro_backend import version as v
    info = v.version_info()
    assert set(info.keys()) == {"version", "codename", "label", "banner"}
    assert info["version"] == "7.0.0"
    assert info["codename"] == "Leviathan"
    assert info["label"] == "V7.0"
    assert info["banner"] == v.VERSION_BANNER
