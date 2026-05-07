"""Tests for Kuro AI V1.0.0 Beta 2 Sovereign Cat version metadata.

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


def test_version_constants_match_v1_sovereign():
    from kuro_backend import version as v
    assert v.VERSION == "1.0.0-beta.5"
    assert v.CODENAME == "Sovereign Chat"
    assert v.VERSION_LABEL == "V1.0 Beta 5"
    assert "V1.0 Beta 5" in v.VERSION_BANNER
    assert "Sovereign Chat" in v.VERSION_BANNER


def test_version_info_payload_shape():
    from kuro_backend import version as v
    info = v.version_info()
    assert set(info.keys()) == {"version", "codename", "label", "banner"}
    assert info["version"] == "1.0.0-beta.5"
    assert info["codename"] == "Sovereign Chat"
    assert info["label"] == "V1.0 Beta 5"
    assert info["banner"] == v.VERSION_BANNER
