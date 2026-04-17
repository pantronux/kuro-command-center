"""Tests for Kuro AI V6.0 Sovereign CVE sentinel inside dreaming_worker."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *a, **kw):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

if "phoenix" not in sys.modules:
    fake_phoenix = types.ModuleType("phoenix")
    fake_phoenix.launch_app = lambda *a, **k: types.SimpleNamespace(
        url="http://x", close=lambda: None,
    )
    sys.modules["phoenix"] = fake_phoenix

from kuro_backend import dreaming_worker, memory_manager  # noqa: E402


@pytest.fixture
def isolated_short_term_db(tmp_path, monkeypatch):
    db_path = tmp_path / "short_term.db"
    monkeypatch.setattr(memory_manager, "SHORT_TERM_DB", str(db_path))
    memory_manager.init_short_term_db()
    yield db_path


def _cve(id_="CVE-2026-0001", cvss=9.1, target="pve01", sw="openssh"):
    return {
        "id": id_,
        "cvss": cvss,
        "severity": "critical" if cvss >= 9 else "high",
        "target_id": target,
        "software": sw,
        "version": "9.2p1",
        "title": id_,
        "description": "remote auth bypass",
        "published": "2026-04-10T12:00:00Z",
        "references": [],
    }


def test_sentinel_disabled_returns_zero_counts(monkeypatch):
    monkeypatch.setenv("KURO_CVE_SENTINEL_ENABLED", "false")
    counts = dreaming_worker._run_cve_sentinel(cycle_id=1, dry_run=True)
    assert counts == {"cves": 0, "persisted": 0, "notified": 0}


def test_openclaw_happy_path_persists_and_notifies(
    isolated_short_term_db, monkeypatch,
):
    monkeypatch.setenv("KURO_CVE_SENTINEL_ENABLED", "true")
    monkeypatch.setenv("KURO_CVE_MAX_ALERTS_PER_CYCLE", "3")
    monkeypatch.setenv("KURO_PROACTIVE_ENABLED", "true")
    monkeypatch.setenv("KURO_PROACTIVE_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("KURO_PROACTIVE_SEVERITY_FLOOR", "warning")

    monkeypatch.setattr(
        dreaming_worker, "_cve_scan_via_openclaw",
        lambda *, min_cvss, max_cves_per_target: (
            [{"kind": "host", "id": "pve01"}],
            [_cve(id_="CVE-2026-0001", cvss=9.1),
             _cve(id_="CVE-2026-0002", cvss=7.4)],
        ),
    )
    persisted = []
    monkeypatch.setattr(
        dreaming_worker, "_persist_cve_alert",
        lambda cve, *, cycle_id: persisted.append(cve["id"]) or True,
    )
    telegrams = []
    from kuro_backend import telegram_notifier
    monkeypatch.setattr(
        telegram_notifier, "send_message",
        lambda text, **kw: telegrams.append(text) or True,
    )

    counts = dreaming_worker._run_cve_sentinel(cycle_id=1, dry_run=False)
    assert counts["cves"] == 2
    assert counts["persisted"] == 2
    assert counts["notified"] == 2
    assert persisted == ["CVE-2026-0001", "CVE-2026-0002"]
    assert any("CVE-2026-0001" in t for t in telegrams)


def test_openclaw_failure_falls_back_to_direct_nvd(
    isolated_short_term_db, monkeypatch,
):
    monkeypatch.setenv("KURO_CVE_SENTINEL_ENABLED", "true")
    monkeypatch.setenv("KURO_PROACTIVE_ENABLED", "true")
    monkeypatch.setenv("KURO_PROACTIVE_TELEGRAM_ENABLED", "true")

    monkeypatch.setattr(
        dreaming_worker, "_cve_scan_via_openclaw",
        lambda *, min_cvss, max_cves_per_target: ([], []),
    )
    monkeypatch.setattr(
        dreaming_worker, "_discover_proxmox_targets_locally",
        lambda: [{"kind": "host", "id": "pve", "software": [
            {"name": "openssh", "version": "9.2"}
        ]}],
    )
    direct_calls = {"count": 0}

    def fake_nvd(targets, *, min_cvss, max_cves_per_target):
        direct_calls["count"] += 1
        return [_cve(id_="CVE-2026-9999", cvss=8.2)]

    monkeypatch.setattr(dreaming_worker, "_cve_scan_via_nvd_direct", fake_nvd)
    monkeypatch.setattr(
        dreaming_worker, "_persist_cve_alert",
        lambda cve, *, cycle_id: True,
    )
    sent = []
    from kuro_backend import telegram_notifier
    monkeypatch.setattr(
        telegram_notifier, "send_message",
        lambda text, **kw: sent.append(text) or True,
    )

    counts = dreaming_worker._run_cve_sentinel(cycle_id=2, dry_run=False)
    assert direct_calls["count"] == 1
    assert counts["cves"] == 1
    assert counts["notified"] == 1


def test_max_alerts_per_cycle_cap_honoured(
    isolated_short_term_db, monkeypatch,
):
    monkeypatch.setenv("KURO_CVE_SENTINEL_ENABLED", "true")
    monkeypatch.setenv("KURO_CVE_MAX_ALERTS_PER_CYCLE", "2")
    monkeypatch.setenv("KURO_PROACTIVE_ENABLED", "true")
    monkeypatch.setenv("KURO_PROACTIVE_TELEGRAM_ENABLED", "true")

    cves = [
        _cve(id_=f"CVE-2026-{i:04d}", cvss=9.5 - i * 0.1)
        for i in range(5)
    ]
    monkeypatch.setattr(
        dreaming_worker, "_cve_scan_via_openclaw",
        lambda *, min_cvss, max_cves_per_target: ([{"id": "pve"}], cves),
    )
    persisted = []
    monkeypatch.setattr(
        dreaming_worker, "_persist_cve_alert",
        lambda cve, *, cycle_id: persisted.append(cve["id"]) or True,
    )
    from kuro_backend import telegram_notifier
    monkeypatch.setattr(
        telegram_notifier, "send_message", lambda text, **kw: True,
    )

    counts = dreaming_worker._run_cve_sentinel(cycle_id=3, dry_run=False)
    assert counts["cves"] == 5  # total discovered
    assert counts["persisted"] == 2  # capped
    assert persisted == ["CVE-2026-0000", "CVE-2026-0001"]


def test_dry_run_does_not_persist_or_notify(
    isolated_short_term_db, monkeypatch,
):
    monkeypatch.setenv("KURO_CVE_SENTINEL_ENABLED", "true")
    monkeypatch.setattr(
        dreaming_worker, "_cve_scan_via_openclaw",
        lambda *, min_cvss, max_cves_per_target: (
            [{"id": "pve"}],
            [_cve(id_="CVE-DRY", cvss=9.0)],
        ),
    )
    persisted = []
    monkeypatch.setattr(
        dreaming_worker, "_persist_cve_alert",
        lambda cve, *, cycle_id: persisted.append(1) or True,
    )
    sent = []
    from kuro_backend import telegram_notifier
    monkeypatch.setattr(
        telegram_notifier, "send_message",
        lambda text, **kw: sent.append(1) or True,
    )
    counts = dreaming_worker._run_cve_sentinel(cycle_id=4, dry_run=True)
    assert counts["cves"] == 1
    assert counts["persisted"] == 0
    assert counts["notified"] == 0
    assert persisted == [] and sent == []


def test_publish_event_uses_security_cve_kind_and_dedup(
    isolated_short_term_db, monkeypatch,
):
    monkeypatch.setenv("KURO_PROACTIVE_ENABLED", "true")
    monkeypatch.setenv("KURO_PROACTIVE_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("KURO_PROACTIVE_SEVERITY_FLOOR", "warning")
    sent = []
    from kuro_backend import telegram_notifier
    monkeypatch.setattr(
        telegram_notifier, "send_message",
        lambda text, **kw: sent.append(text) or True,
    )
    cve = _cve(id_="CVE-DEDUP", cvss=9.2, target="pve01")
    assert dreaming_worker._publish_cve_event(cve) is True
    assert len(sent) == 1
    # Second call with identical CVE id + target => dedup'd.
    assert dreaming_worker._publish_cve_event(cve) is False
    assert len(sent) == 1


def test_persist_cve_alert_writes_chroma_metadata(monkeypatch):
    captured = {}

    def fake_add_long_term_v2(content, metadata=None):
        captured["content"] = content
        captured["metadata"] = metadata

    from kuro_backend import memory_manager as mm
    monkeypatch.setattr(mm, "add_long_term_v2", fake_add_long_term_v2)
    cve = _cve(id_="CVE-CHROMA", cvss=8.1, target="vm101")
    assert dreaming_worker._persist_cve_alert(cve, cycle_id=7) is True
    assert "CVE-CHROMA" in captured["content"]
    md = captured["metadata"]
    assert md["tag"] == "cve-alert"
    assert md["source"] == "cve_sentinel"
    assert md["cve_id"] == "CVE-CHROMA"
    assert md["target_id"] == "vm101"
    assert md["cvss"] == 8.1
    assert md["cycle_id"] == 7
