"""Tests for Kuro AI Pre V.2.0.0 Beta 1 Runtime Sovereign version metadata.

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


def test_version_constants_match_pre_v2_runtime_sovereign():
    from kuro_backend import version as v
    assert v.VERSION == "2.0.0-beta.1-pre"
    assert v.CODENAME == "Runtime Sovereign"
    assert v.VERSION_LABEL == "Pre V.2.0.0 Beta 1"
    assert "Pre V.2.0.0 Beta 1" in v.VERSION_BANNER
    assert "Runtime Sovereign" in v.VERSION_BANNER


def test_version_info_payload_shape():
    from kuro_backend import version as v
    info = v.version_info()
    assert set(info.keys()) == {"version", "codename", "label", "banner"}
    assert info["version"] == "2.0.0-beta.1-pre"
    assert info["codename"] == "Runtime Sovereign"
    assert info["label"] == "Pre V.2.0.0 Beta 1"
    assert info["banner"] == v.VERSION_BANNER
