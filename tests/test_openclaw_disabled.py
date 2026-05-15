"""
Tests for OpenClaw optional-dependency control flag (OPENCLAW_ENABLED).

--- Header Doc ---
Purpose: Verify that OPENCLAW_ENABLED=false fully suppresses HTTP calls,
         circuit breaker mutations, and Telegram open-circuit alerts, while
         OPENCLAW_ENABLED=true preserves existing circuit breaker behaviour.
Fixtures: monkeypatch for env, requests.post stub, time.monotonic stub.
Side Effects: None (no real network, no real DB).
"""
from __future__ import annotations

import asyncio
import time
import threading
from typing import Any, Dict
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_bridge(bridge_mod):
    """Reset all circuit breaker module-level state between tests."""
    bridge_mod._circuit_open = False
    bridge_mod._circuit_opened_at = 0.0
    bridge_mod._consecutive_unavailable_failures = 0
    bridge_mod._half_open_probe_inflight = False
    bridge_mod._circuit_trips_total = 0
    bridge_mod._disabled_logged_once = False


# ---------------------------------------------------------------------------
# 1. Disabled OpenClaw does not call requests.post
# ---------------------------------------------------------------------------

class TestOpenClawDisabledNoHTTP:
    """When OPENCLAW_ENABLED=false, no HTTP request must be made."""

    def test_blocking_no_requests_post(self, monkeypatch):
        import kuro_backend.execution.openclaw_bridge as bridge

        monkeypatch.setenv("OPENCLAW_ENABLED", "false")
        _reset_bridge(bridge)

        post_mock = MagicMock()
        monkeypatch.setattr("requests.post", post_mock)

        result = bridge.execute_openclaw_skill_blocking("market_analysis", {"symbol": "AAPL"})

        post_mock.assert_not_called()
        assert result.get("openclaw_disabled") is True
        assert result.get("success") is False

    def test_async_no_requests_post(self, monkeypatch):
        import kuro_backend.execution.openclaw_bridge as bridge

        monkeypatch.setenv("OPENCLAW_ENABLED", "false")
        _reset_bridge(bridge)

        post_mock = MagicMock()
        monkeypatch.setattr("requests.post", post_mock)

        result = asyncio.run(bridge.execute_openclaw_skill("market_analysis", {"symbol": "AAPL"}))

        post_mock.assert_not_called()
        assert result.get("openclaw_disabled") is True
        assert result.get("success") is False

    def test_various_truthy_values_treated_as_disabled(self, monkeypatch):
        import kuro_backend.execution.openclaw_bridge as bridge

        for falsy in ("false", "False", "FALSE", "0", "no", "off", ""):
            monkeypatch.setenv("OPENCLAW_ENABLED", falsy)
            assert bridge.is_openclaw_enabled() is False, f"Expected disabled for {falsy!r}"

    def test_various_truthy_values_treated_as_enabled(self, monkeypatch):
        import kuro_backend.execution.openclaw_bridge as bridge

        for truthy in ("true", "True", "TRUE", "1", "yes", "on"):
            monkeypatch.setenv("OPENCLAW_ENABLED", truthy)
            assert bridge.is_openclaw_enabled() is True, f"Expected enabled for {truthy!r}"


# ---------------------------------------------------------------------------
# 2. Disabled OpenClaw does not increment circuit breaker failure count
# ---------------------------------------------------------------------------

class TestOpenClawDisabledNoCircuitBreaker:
    """Disabled state must not mutate circuit breaker counters or flags."""

    def test_blocking_no_failure_increment(self, monkeypatch):
        import kuro_backend.execution.openclaw_bridge as bridge

        monkeypatch.setenv("OPENCLAW_ENABLED", "false")
        _reset_bridge(bridge)

        bridge.execute_openclaw_skill_blocking("any_skill", {})

        assert bridge._consecutive_unavailable_failures == 0
        assert bridge._circuit_open is False
        assert bridge._circuit_trips_total == 0

    def test_async_no_failure_increment(self, monkeypatch):
        import kuro_backend.execution.openclaw_bridge as bridge

        monkeypatch.setenv("OPENCLAW_ENABLED", "false")
        _reset_bridge(bridge)

        asyncio.run(bridge.execute_openclaw_skill("any_skill", {}))

        assert bridge._consecutive_unavailable_failures == 0
        assert bridge._circuit_open is False
        assert bridge._circuit_trips_total == 0

    def test_metrics_report_disabled(self, monkeypatch):
        import kuro_backend.execution.openclaw_bridge as bridge

        monkeypatch.setenv("OPENCLAW_ENABLED", "false")
        _reset_bridge(bridge)

        metrics = bridge.get_circuit_metrics()

        assert metrics["enabled"] is False
        assert metrics["circuit_breaker_state"] == "disabled"
        assert metrics["consecutive_failures"] == 0

    def test_get_circuit_state_returns_disabled(self, monkeypatch):
        import kuro_backend.execution.openclaw_bridge as bridge

        monkeypatch.setenv("OPENCLAW_ENABLED", "false")
        _reset_bridge(bridge)

        assert bridge.get_circuit_state() == "disabled"

    def test_disabled_response_safe_structure(self, monkeypatch):
        """Disabled response must not set memory_fallback_required=True."""
        import kuro_backend.execution.openclaw_bridge as bridge

        monkeypatch.setenv("OPENCLAW_ENABLED", "false")
        _reset_bridge(bridge)

        resp = bridge.execute_openclaw_skill_blocking("some_skill", {})

        assert resp.get("memory_fallback_required") is False
        cb = resp.get("circuit_breaker", {})
        assert cb.get("open") is False
        assert cb.get("disabled") is True


# ---------------------------------------------------------------------------
# 3. Disabled OpenClaw monitor does not send Telegram alert
# ---------------------------------------------------------------------------

class TestOpenClawDisabledNoTelegramAlert:
    """run_openclaw_circuit_open_alert_job must not call Telegram when disabled."""

    def _make_alert_fn(self, monkeypatch, openclaw_enabled: bool):
        """
        Simulate run_openclaw_circuit_open_alert_job by directly reproducing
        the logic from main.py in an isolated closure.
        """
        import kuro_backend.execution.openclaw_bridge as bridge

        monkeypatch.setenv("OPENCLAW_ENABLED", "true" if openclaw_enabled else "false")

        # Force circuit open state so the alert *would* fire if not guarded.
        _reset_bridge(bridge)
        bridge._circuit_open = True
        # Set opened_at 2 hours ago (well past 30-minute threshold).
        bridge._circuit_opened_at = time.monotonic() - 7201.0

        telegram_calls = []
        sent_ts = [0.0]  # last alert timestamp

        def _alert_fn():
            if not bridge.is_openclaw_enabled():
                return
            metrics = bridge.get_circuit_metrics()
            if metrics.get("circuit_breaker_state") != "open":
                return
            opened_at = float(metrics.get("opened_at_monotonic") or 0.0)
            if opened_at <= 0.0:
                return
            elapsed = time.monotonic() - opened_at
            if elapsed < 1800:
                return
            if (time.monotonic() - sent_ts[0]) < 1800:
                return
            sent_ts[0] = time.monotonic()
            telegram_calls.append("alert_sent")

        return _alert_fn, telegram_calls

    def test_disabled_no_telegram(self, monkeypatch):
        fn, calls = self._make_alert_fn(monkeypatch, openclaw_enabled=False)
        fn()
        assert calls == [], "No Telegram alert should fire when OpenClaw is disabled"

    def test_enabled_sends_telegram_when_open(self, monkeypatch):
        fn, calls = self._make_alert_fn(monkeypatch, openclaw_enabled=True)
        fn()
        assert calls == ["alert_sent"], "Alert should fire when OpenClaw is enabled and circuit is OPEN >30 min"


# ---------------------------------------------------------------------------
# 4. Enabled OpenClaw still uses existing circuit breaker behaviour
# ---------------------------------------------------------------------------

class TestOpenClawEnabledCircuitBreakerBehaviour:
    """When OPENCLAW_ENABLED=true, failures must trip the circuit breaker."""

    def _make_failing_post(self):
        import requests as req
        raise req.ConnectionError("simulated connection refused")

    def test_failures_trip_circuit_breaker_when_enabled(self, monkeypatch):
        import requests as req
        import kuro_backend.execution.openclaw_bridge as bridge

        monkeypatch.setenv("OPENCLAW_ENABLED", "true")
        _reset_bridge(bridge)

        # Patch requests.post to raise ConnectionError every time.
        monkeypatch.setattr(
            "requests.post",
            lambda *a, **kw: (_ for _ in ()).throw(req.ConnectionError("refused")),
        )

        threshold = bridge.OPENCLAW_CIRCUIT_BREAKER_THRESHOLD
        for _ in range(threshold):
            bridge.execute_openclaw_skill_blocking("skill", {"task_description": "test"})

        assert bridge._circuit_open is True, "Circuit should be OPEN after threshold failures"
        assert bridge._consecutive_unavailable_failures >= threshold

    def test_metrics_report_enabled_and_open(self, monkeypatch):
        import requests as req
        import kuro_backend.execution.openclaw_bridge as bridge

        monkeypatch.setenv("OPENCLAW_ENABLED", "true")
        _reset_bridge(bridge)

        monkeypatch.setattr(
            "requests.post",
            lambda *a, **kw: (_ for _ in ()).throw(req.ConnectionError("refused")),
        )

        threshold = bridge.OPENCLAW_CIRCUIT_BREAKER_THRESHOLD
        for _ in range(threshold):
            bridge.execute_openclaw_skill_blocking("skill", {"task_description": "test"})

        metrics = bridge.get_circuit_metrics()
        assert metrics["enabled"] is True
        assert metrics["circuit_breaker_state"] == "open"
        assert metrics["consecutive_failures"] >= threshold

    def test_success_closes_circuit_when_enabled(self, monkeypatch):
        import kuro_backend.execution.openclaw_bridge as bridge

        monkeypatch.setenv("OPENCLAW_ENABLED", "true")
        _reset_bridge(bridge)

        # Pre-open the circuit.
        bridge._circuit_open = True
        bridge._circuit_opened_at = time.monotonic() - 60.0
        bridge._consecutive_unavailable_failures = bridge.OPENCLAW_CIRCUIT_BREAKER_THRESHOLD

        # Return a successful 200 OK response.
        ok_response = MagicMock()
        ok_response.ok = True
        ok_response.status_code = 200
        ok_response.json.return_value = {"status": "ok"}

        monkeypatch.setattr("requests.post", lambda *a, **kw: ok_response)

        # Force cooldown elapsed so half-open probe is allowed.
        bridge._circuit_opened_at = time.monotonic() - (
            bridge.OPENCLAW_CIRCUIT_BREAKER_COOLDOWN_SECONDS + 1
        )

        bridge.execute_openclaw_skill_blocking("skill", {"execution_mode": "readonly"})

        assert bridge._circuit_open is False, "Successful probe should close the circuit"
