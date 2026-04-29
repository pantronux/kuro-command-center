"""Tests for Kuro AI V7.2.1 Natural Agency version metadata.

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


def test_version_constants_match_v7_agency():
    from kuro_backend import version as v
    assert v.VERSION == "7.2.1"
    assert v.CODENAME == "Sovereign Leviathan"
    assert v.VERSION_LABEL == "V7.2"
    assert "V7.2" in v.VERSION_BANNER
    assert "Natural Agency" in v.VERSION_BANNER


def test_version_info_payload_shape():
    from kuro_backend import version as v
    info = v.version_info()
    assert set(info.keys()) == {"version", "codename", "label", "banner"}
    assert info["version"] == "7.2.1"
    assert info["codename"] == "Sovereign Leviathan"
    assert info["label"] == "V7.2"
    assert info["banner"] == v.VERSION_BANNER
