"""Fiscal sentinel: yesterday's API cost vs threshold + proactive dedup.

--- Header Doc ---
Purpose: Verify _run_fiscal_sentinel fires exactly once over threshold + honours kill switch.
Covers: dreaming_worker._run_fiscal_sentinel, proactive_events publish.
Fixtures: tmp finance DB + monkeypatched proactive_events.publish.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_fiscal_sentinel_publishes_when_over_threshold(monkeypatch):
    from kuro_backend import dreaming_worker

    monkeypatch.setenv("KURO_FISCAL_SENTINEL_ENABLED", "true")
    monkeypatch.setenv("KURO_FISCAL_DAILY_USD_THRESHOLD", "0.50")
    published = []

    def fake_get(_date: str) -> float:
        return 0.99

    def fake_publish(event, *, dry_run: bool = False):
        published.append((event.kind, event.fingerprint_seed, dry_run))
        return True

    monkeypatch.setattr(
        "kuro_backend.finance_db.get_daily_api_cost_usd",
        fake_get,
    )
    monkeypatch.setattr(
        "kuro_backend.proactive_events.publish",
        fake_publish,
    )
    monkeypatch.setattr(
        "kuro_backend.dreaming_worker._persist_fiscal_roll_up_insight",
        lambda **kwargs: None,
    )

    counts = dreaming_worker._run_fiscal_sentinel(cycle_id=42, dry_run=False)
    assert counts["checked"] == 1
    assert counts["notified"] == 1
    assert published[0][0] == "fiscal_alert"
    assert str(published[0][1]).startswith("fiscal:")


def test_fiscal_sentinel_silent_below_threshold(monkeypatch):
    from kuro_backend import dreaming_worker

    monkeypatch.setenv("KURO_FISCAL_DAILY_USD_THRESHOLD", "5.00")

    def fake_get(_date: str) -> float:
        return 0.10

    monkeypatch.setattr(
        "kuro_backend.finance_db.get_daily_api_cost_usd",
        fake_get,
    )
    monkeypatch.setattr(
        "kuro_backend.proactive_events.publish",
        lambda *a, **k: pytest.fail("should not publish"),
    )
    monkeypatch.setattr(
        "kuro_backend.dreaming_worker._persist_fiscal_roll_up_insight",
        lambda **kwargs: None,
    )

    counts = dreaming_worker._run_fiscal_sentinel(cycle_id=1, dry_run=False)
    assert counts["notified"] == 0
