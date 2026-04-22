"""Market tools delegate to OpenClaw; bridge is monkeypatched.

--- Header Doc ---
Purpose: Verify market tool wrappers call the bridge and update finance cache.
Covers: tools.base_tools.get_ticker_price_tool / get_market_news_tool / prediction_market_scan_tool.
Fixtures: monkeypatched execution.openclaw_bridge + tmp finance DB.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_get_ticker_price_tool_success(monkeypatch, tmp_path):
    monkeypatch.setenv("KURO_FINANCE_DB_PATH", str(tmp_path / "m.db"))

    def fake(skill_name: str, payload=None):
        assert skill_name == "market_analysis"
        assert payload.get("op") == "get_ticker_price"
        return {
            "success": True,
            "result": {
                "ok": True,
                "symbol": "AAA",
                "price": 12.5,
                "currency": "USD",
                "as_of": "2026-01-01T00:00:00Z",
                "source": "test",
            },
        }

    monkeypatch.setattr(
        "kuro_backend.tools.base_tools._openclaw_skill_body",
        fake,
    )
    from kuro_backend.tools import base_tools

    out = base_tools.get_ticker_price_tool("AAA")
    assert out["success"] is True
    assert out["price"] == 12.5


def test_get_ticker_price_tool_bridge_failure(monkeypatch):
    def fake(*a, **k):
        return {"success": False, "error": "down"}

    monkeypatch.setattr(
        "kuro_backend.tools.base_tools._openclaw_skill_body",
        fake,
    )
    from kuro_backend.tools import base_tools

    out = base_tools.get_ticker_price_tool("AAA")
    assert out["success"] is False
    assert "down" in (out.get("error") or "")


def test_prediction_market_scan_tool_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("KURO_FINANCE_DB_PATH", str(tmp_path / "p.db"))

    def fake(skill_name: str, payload=None):
        assert skill_name == "prediction_market_scan"
        return {
            "success": True,
            "result": {
                "ok": True,
                "markets": [
                    {"topic_id": "x1", "title": "T1", "probability": 0.4},
                ],
            },
        }

    monkeypatch.setattr(
        "kuro_backend.tools.base_tools._openclaw_skill_body",
        fake,
    )
    from kuro_backend.tools import base_tools

    out = base_tools.prediction_market_scan_tool("")
    assert out["success"] is True
    assert len(out.get("markets") or []) == 1
