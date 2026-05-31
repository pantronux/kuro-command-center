from __future__ import annotations

from kuro_backend.krc_profile import is_krc_scheduler_enabled


def test_krc_role_scheduler_split(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "krc")
    monkeypatch.delenv("KURO_KRC_SCHEDULER_TELEGRAM_ENABLED", raising=False)
    monkeypatch.delenv("KURO_KRC_SCHEDULER_MARKET_ENABLED", raising=False)

    assert is_krc_scheduler_enabled("backup") is True
    assert is_krc_scheduler_enabled("memory_decay") is True
    assert is_krc_scheduler_enabled("file_retention") is True
    assert is_krc_scheduler_enabled("market") is False
    assert is_krc_scheduler_enabled("telegram") is False
    assert is_krc_scheduler_enabled("daily_briefing") is False


def test_kcc_role_scheduler_split(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "kcc")

    assert is_krc_scheduler_enabled("backup") is True
    assert is_krc_scheduler_enabled("market") is True
    assert is_krc_scheduler_enabled("telegram") is True
    assert is_krc_scheduler_enabled("daily_briefing") is False


def test_knowledge_role_scheduler_split(monkeypatch):
    monkeypatch.setenv("KURO_APP_ROLE", "knowledge")

    assert is_krc_scheduler_enabled("file_retention") is True
    assert is_krc_scheduler_enabled("market") is False
    assert is_krc_scheduler_enabled("telegram") is False
