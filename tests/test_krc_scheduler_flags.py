from __future__ import annotations

import os
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WORKING_DIR", str(PROJECT_ROOT))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *args, **kwargs):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

if "phoenix" not in sys.modules:
    fake_phoenix = types.ModuleType("phoenix")

    class _FakePhoenixApp:
        url = "http://localhost:6006"

        def close(self):
            return None

    fake_phoenix.launch_app = lambda *args, **kwargs: _FakePhoenixApp()
    sys.modules["phoenix"] = fake_phoenix

import main


class FakeScheduler:
    instances = []

    def __init__(self, *args, **kwargs):
        self.jobs = []
        self.started = False
        FakeScheduler.instances.append(self)

    def add_job(self, func, trigger, *args, **kwargs):
        self.jobs.append(kwargs.get("id"))

    def start(self):
        self.started = True

    def shutdown(self):
        self.started = False

    def get_job(self, job_id):
        return None


def _patch_scheduler(monkeypatch):
    import apscheduler.schedulers.background as background

    FakeScheduler.instances.clear()
    monkeypatch.setattr(background, "BackgroundScheduler", FakeScheduler)
    monkeypatch.setattr(main, "_reminder_scheduler", None)
    monkeypatch.setattr(main, "_evaluation_scheduler", None)
    monkeypatch.setattr(main, "_hardware_sentinel_scheduler", None)


def test_krc_scheduler_disables_daily_market_and_proactive_but_keeps_telegram_ops(monkeypatch):
    _patch_scheduler(monkeypatch)
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    monkeypatch.delenv("KURO_KRC_SCHEDULER_MARKET_ENABLED", raising=False)
    monkeypatch.delenv("KURO_KRC_SCHEDULER_TELEGRAM_ENABLED", raising=False)
    monkeypatch.delenv("KURO_KRC_SCHEDULER_DAILY_BRIEFING_ENABLED", raising=False)
    monkeypatch.delenv("KURO_KRC_SCHEDULER_PROACTIVE_ENABLED", raising=False)
    monkeypatch.delenv("KURO_KRC_SCHEDULER_FITNESS_ENABLED", raising=False)
    monkeypatch.setenv("KURO_FITNESS_ENABLED", "true")

    main.start_reminder_scheduler()

    jobs = set(main._reminder_scheduler.jobs)
    assert {
        "nightly_backup",
        "memory_decay_job",
        "file_retention_cycle",
        "weekly_research_ledger_prune",
        "telegram_operational_digest",
        "retry_failed_telegram_notifications",
        "openclaw_circuit_open_alert",
    } <= jobs
    assert "daily_intelligence_briefing" not in jobs
    assert "price_ticker_update" not in jobs
    assert "market_sentinel_scan" not in jobs
    assert "kuro_dreaming_cycle" not in jobs
    assert "kuro_fitness_sentinel" not in jobs


def test_krc_scheduler_optional_jobs_can_be_enabled(monkeypatch):
    _patch_scheduler(monkeypatch)
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    monkeypatch.setenv("KURO_KRC_SCHEDULER_MARKET_ENABLED", "true")
    monkeypatch.setenv("KURO_KRC_SCHEDULER_DAILY_BRIEFING_ENABLED", "true")

    main.start_reminder_scheduler()

    jobs = set(main._reminder_scheduler.jobs)
    assert "daily_intelligence_briefing" in jobs
    assert "price_ticker_update" in jobs
    assert "market_sentinel_scan" in jobs
    assert "telegram_operational_digest" in jobs
    assert "retry_failed_telegram_notifications" in jobs


def test_krc_scheduler_telegram_ops_can_be_disabled(monkeypatch):
    _patch_scheduler(monkeypatch)
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    monkeypatch.setenv("KURO_KRC_SCHEDULER_TELEGRAM_ENABLED", "false")

    main.start_reminder_scheduler()

    jobs = set(main._reminder_scheduler.jobs)
    assert "telegram_operational_digest" not in jobs
    assert "retry_failed_telegram_notifications" not in jobs
    assert "openclaw_circuit_open_alert" not in jobs


def test_krc_evaluation_and_hardware_schedulers_skip_by_default(monkeypatch):
    _patch_scheduler(monkeypatch)
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")

    main.start_evaluation_scheduler()
    main.start_hardware_sentinel()

    assert main._evaluation_scheduler is None
    assert main._hardware_sentinel_scheduler is None
    assert FakeScheduler.instances == []
