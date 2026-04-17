"""Tests for Kuro AI V6.1 Sovereign version metadata."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_version_constants_match_v6_sovereign():
    from kuro_backend import version as v
    assert v.VERSION == "6.1.0"
    assert v.CODENAME == "Sovereign"
    assert v.VERSION_LABEL == "V6.1"
    assert "V6.1" in v.VERSION_BANNER
    assert "Sovereign" in v.VERSION_BANNER


def test_version_info_payload_shape():
    from kuro_backend import version as v
    info = v.version_info()
    assert set(info.keys()) == {"version", "codename", "label", "banner"}
    assert info["version"] == "6.1.0"
    assert info["codename"] == "Sovereign"
    assert info["label"] == "V6.1"
    assert info["banner"] == v.VERSION_BANNER
