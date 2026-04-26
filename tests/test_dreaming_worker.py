"""Tests for Kuro AI V6.0 Sovereign Autonomous Memory Dreaming worker.

Covers:
  - SQLite schema: dreaming_locks / dreaming_cycles / dream_notifications.
  - Lease acquire/release + contention.
  - Idle gate honoured when last short_term is recent; force=True bypasses.
  - Collector 24h windowing: rows older than cutoff are dropped.
  - Reflection JSON coercion: malformed / partial payloads -> safe fallback.
  - Enrichment fallback: OpenClaw raises -> Serper called.
  - Chroma persistence carries tag=dream-insight metadata.
  - SSoT bump gated by ssot_bump_recommended + kind + confidence.
  - Telegram dedup: second fire with same fingerprint is a no-op.
  - Kill switches: KURO_DREAMING_ENABLED=false short-circuits cycle.

--- Header Doc ---
Purpose: Verify dreaming_worker cycle end-to-end (lease, collect, reflect, enrich, persist, bump, dedup).
Covers: kuro_backend.dreaming_worker (most _run_* helpers).
Fixtures: tmp sqlite DBs, monkeypatched Gemini/OpenClaw/Serper/Telegram.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Stub optional deps so the import chain stays minimal.
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

    fake_phoenix.launch_app = lambda *a, **k: _FakePhoenixApp()
    sys.modules["phoenix"] = fake_phoenix


from kuro_backend import dreaming_worker
from kuro_backend import memory_manager
from kuro_backend.dreaming_worker import (
    Finding,
    _coerce_findings,
    _finding_fingerprint,
    _maybe_bump_ssot,
    _maybe_notify,
    _search_with_fallback,
    collect_last_24h,
)


# ---------------------------------------------------------------------------
# Fixture: isolated short_term DB per test
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_short_term_db(tmp_path, monkeypatch):
    db_path = tmp_path / "short_term.db"
    monkeypatch.setattr(memory_manager, "SHORT_TERM_DB", str(db_path))
    memory_manager.init_short_term_db()
    yield db_path


# ---------------------------------------------------------------------------
# Schema + lease lifecycle
# ---------------------------------------------------------------------------

def test_schema_creates_dreaming_tables(isolated_short_term_db):
    import sqlite3
    conn = sqlite3.connect(isolated_short_term_db)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('dreaming_locks','dreaming_cycles','dream_notifications')"
        ).fetchall()
    finally:
        conn.close()
    names = {r[0] for r in rows}
    assert names == {"dreaming_locks", "dreaming_cycles", "dream_notifications"}


def test_lease_acquire_release_and_contention(isolated_short_term_db):
    assert memory_manager.acquire_dreaming_lease("dreaming", "holderA", 900) is True
    # Second holder cannot steal a live lease.
    assert memory_manager.acquire_dreaming_lease("dreaming", "holderB", 900) is False
    memory_manager.release_dreaming_lease("dreaming", "holderA")
    # After release any holder can acquire.
    assert memory_manager.acquire_dreaming_lease("dreaming", "holderB", 900) is True


def test_lease_reacquire_after_stale(isolated_short_term_db):
    # Insert a stale lease directly so we can prove stale rows are overwritten.
    import sqlite3
    expired = (datetime.now() - timedelta(seconds=5)).isoformat(timespec="seconds")
    conn = sqlite3.connect(isolated_short_term_db)
    try:
        conn.execute(
            "INSERT INTO dreaming_locks (name, leased_by, lease_expires_at) "
            "VALUES (?, ?, ?)",
            ("dreaming", "ghost", expired),
        )
        conn.commit()
    finally:
        conn.close()
    assert memory_manager.acquire_dreaming_lease("dreaming", "fresh", 900) is True


# ---------------------------------------------------------------------------
# Collector windowing
# ---------------------------------------------------------------------------

def test_collect_last_24h_windows_summaries_and_ledger(isolated_short_term_db):
    memory_manager.upsert_short_term_summary_json(
        "advisor", last_entry_id=10,
        summary_json={
            "topic": "PhD deep dive",
            "decisions": ["pick graph transformer baseline"],
            "novelty_points": ["novel loss fn"],
            "technical_specs": [],
            "compliance_refs": [],
            "open_questions": [],
        },
        fallback_text="PhD deep dive",
    )
    memory_manager.append_research_ledger(
        "advisor", "novelty_points", "new benchmark hit", source_entry_id=10,
    )

    # Manually age one ledger row past the cutoff.
    import sqlite3
    old = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
    conn = sqlite3.connect(isolated_short_term_db)
    try:
        conn.execute(
            "INSERT INTO research_ledger (persona_scope, kind, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("advisor", "decisions", "ancient decision", old),
        )
        conn.commit()
    finally:
        conn.close()

    corpus = collect_last_24h(24)
    ledger_contents = [row["content"] for row in corpus["ledger"]]
    assert "new benchmark hit" in ledger_contents
    assert "ancient decision" not in ledger_contents
    assert any(s["topic"] == "PhD deep dive" for s in corpus["summaries"])
    assert "advisor" in corpus["personas_active"]


# ---------------------------------------------------------------------------
# Reflection coercion
# ---------------------------------------------------------------------------

def test_coerce_findings_accepts_dict_payload():
    payload = {
        "overall_risk": "medium",
        "findings": [
            {
                "id": "f1",
                "kind": "inconsistency",
                "persona_scope": "advisor",
                "description": "Jadwal bentrok di kalender",
                "confidence": 0.42,
                "evidence": ["chat 12:00", "chat 14:00"],
                "search_query": "konflik jadwal kuliah ITB",
                "ssot_bump_recommended": True,
                "suggested_fix": "Rescan reminders",
            },
            {"kind": "unknown_kind", "persona_scope": "x", "description": "d", "confidence": 0.9},
            {"kind": "deep_research", "persona_scope": "tactical", "description": "", "confidence": 0.5},
        ],
    }
    findings, risk = _coerce_findings(payload)
    assert risk == "medium"
    assert len(findings) == 1
    assert findings[0].id == "f1"
    assert findings[0].kind == "inconsistency"
    assert findings[0].ssot_bump_recommended is True


def test_coerce_findings_handles_malformed_string():
    findings, risk = _coerce_findings("not json at all")
    assert findings == []
    assert risk == "low"


# ---------------------------------------------------------------------------
# Search fallback
# ---------------------------------------------------------------------------

def test_search_fallback_to_serper_when_openclaw_raises(monkeypatch):
    def _boom(skill, payload=None):
        raise RuntimeError("openclaw down")

    fake_module = types.ModuleType("kuro_backend.execution.service")
    fake_module.execute_openclaw_skill_sync = _boom
    monkeypatch.setitem(
        sys.modules, "kuro_backend.execution.service", fake_module,
    )

    called = {}

    def _fake_serper(query, search_type="search", num_results=10):
        called["query"] = query
        return {"organic_results": [
            {"title": "Paper A", "snippet": "Key insight", "link": "https://x/a"},
        ]}

    fake_serper_mod = types.ModuleType("kuro_backend.serper_tool")
    fake_serper_mod.serper_search = _fake_serper
    monkeypatch.setitem(sys.modules, "kuro_backend.serper_tool", fake_serper_mod)

    results, source = _search_with_fallback("quantum drift 2026")
    assert source == "serper"
    assert called["query"] == "quantum drift 2026"
    assert results[0]["title"] == "Paper A"


def test_search_openclaw_happy_path(monkeypatch):
    def _ok(skill, payload=None):
        assert skill == "google_search"
        return {
            "status": "ok",
            "results": [{"title": "Hit", "snippet": "snip", "link": "https://x"}],
        }

    fake_module = types.ModuleType("kuro_backend.execution.service")
    fake_module.execute_openclaw_skill_sync = _ok
    monkeypatch.setitem(sys.modules, "kuro_backend.execution.service", fake_module)

    results, source = _search_with_fallback("anything")
    assert source == "openclaw"
    assert results[0]["title"] == "Hit"


# ---------------------------------------------------------------------------
# SSoT bump gating
# ---------------------------------------------------------------------------

def test_ssot_bump_gated_by_confidence(monkeypatch):
    calls = []

    def _fake_bump():
        calls.append("bump")

    # Patch the real submodule attribute: replacing sys.modules is order-dependent
    # once another test has imported kuro_backend.services.core_service.
    monkeypatch.setattr(
        "kuro_backend.services.core_service.bump_data_revision",
        _fake_bump,
    )

    low = Finding(
        kind="inconsistency", persona_scope="advisor",
        description="x", confidence=0.3, ssot_bump_recommended=True,
    )
    high = Finding(
        kind="inconsistency", persona_scope="advisor",
        description="x", confidence=0.8, ssot_bump_recommended=True,
    )
    unrelated = Finding(
        kind="unresolved_question", persona_scope="advisor",
        description="x", confidence=0.9, ssot_bump_recommended=True,
    )

    assert _maybe_bump_ssot(low, cycle_id=1, dry_run=False) is False
    assert _maybe_bump_ssot(unrelated, cycle_id=1, dry_run=False) is False
    assert _maybe_bump_ssot(high, cycle_id=1, dry_run=False) is True
    assert calls == ["bump"]


def test_ssot_bump_dry_run_skips_bump(monkeypatch):
    called = {"n": 0}

    def _fake_bump():
        called["n"] += 1

    monkeypatch.setattr(
        "kuro_backend.services.core_service.bump_data_revision",
        _fake_bump,
    )

    finding = Finding(
        kind="inconsistency", persona_scope="advisor",
        description="x", confidence=0.9, ssot_bump_recommended=True,
    )
    assert _maybe_bump_ssot(finding, cycle_id=1, dry_run=True) is False
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# Telegram notify + dedup
# ---------------------------------------------------------------------------

def test_notify_deduped_by_fingerprint(isolated_short_term_db, monkeypatch):
    sends = []

    def _fake_send(persona, desc, *, finding_id="", dry_run=False):
        sends.append((persona, desc, finding_id))
        return True

    import kuro_backend.telegram_notifier as tn
    monkeypatch.setattr(tn, "send_dream_inconsistency", _fake_send)

    f = Finding(
        kind="inconsistency", persona_scope="advisor",
        description="Data jadwal tidak konsisten antar persona.",
        confidence=0.6,
    )
    assert _maybe_notify(f, dry_run=False) is True
    # Second call must dedup.
    assert _maybe_notify(f, dry_run=False) is False
    assert len(sends) == 1


def test_notify_skips_non_inconsistency_kind(isolated_short_term_db, monkeypatch):
    called = {"n": 0}

    def _fake_send(*a, **k):
        called["n"] += 1
        return True

    import kuro_backend.telegram_notifier as tn
    monkeypatch.setattr(tn, "send_dream_inconsistency", _fake_send)

    f = Finding(
        kind="unresolved_question", persona_scope="advisor",
        description="Pertanyaan X belum terjawab.", confidence=0.9,
    )
    assert _maybe_notify(f, dry_run=False) is False
    assert called["n"] == 0


def test_finding_fingerprint_stable():
    f1 = Finding(kind="inconsistency", persona_scope="advisor", description="abc", confidence=0.5)
    f2 = Finding(kind="inconsistency", persona_scope="advisor", description="abc", confidence=0.9)
    # Fingerprint ignores confidence, only depends on persona|kind|description.
    assert _finding_fingerprint(f1) == _finding_fingerprint(f2)


# ---------------------------------------------------------------------------
# Chroma metadata carries #dream-insight
# ---------------------------------------------------------------------------

def test_persist_dream_insight_writes_tag(monkeypatch, isolated_short_term_db):
    captured = {}

    class FakeMemoryClient:
        def store_memories(self, memories):
            captured["memories"] = memories
            return True

    class FakePerpetualMemory:
        def get_memory_client(self):
            return FakeMemoryClient()

    from kuro_backend import perpetual_memory
    monkeypatch.setattr(perpetual_memory, "get_memory_client", FakePerpetualMemory().get_memory_client)

    finding = Finding(
        kind="deep_research", persona_scope="advisor",
        description="Perlu perdalam topik X.", confidence=0.4, id="fD",
    )
    ok = dreaming_worker._persist_dream_insight(
        finding, "Ringkasan dari 3 paper.",
        source_label="openclaw", cycle_id=42,
    )
    assert ok is True
    assert captured["memories"][0]["metadata"]["tag"] == "dream-insight"
    assert captured["memories"][0]["metadata"]["source"] == "dream_insight"
    assert captured["memories"][0]["metadata"]["cycle_id"] == 42
    assert captured["memories"][0]["metadata"]["finding_kind"] == "deep_research"
    assert captured["memories"][0]["memory"].startswith("[DREAM-INSIGHT]")


# ---------------------------------------------------------------------------
# Orchestrator: kill switch + idle gate
# ---------------------------------------------------------------------------

def test_run_cycle_returns_disabled_when_kill_switch_off(monkeypatch, isolated_short_term_db):
    monkeypatch.setenv("KURO_DREAMING_ENABLED", "false")
    audit = dreaming_worker.run_dreaming_cycle()
    assert audit["status"] == "disabled"


def test_run_cycle_skipped_when_not_idle(monkeypatch, isolated_short_term_db):
    monkeypatch.setenv("KURO_DREAMING_ENABLED", "true")
    monkeypatch.setenv("KURO_DREAMING_IDLE_MIN", "120")
    # Write a short_term row with a very fresh timestamp.
    import sqlite3
    conn = sqlite3.connect(isolated_short_term_db)
    try:
        conn.execute(
            "INSERT INTO short_term (role, content, persona_scope, timestamp) "
            "VALUES (?, ?, ?, ?)",
            ("user", "hi", "advisor", datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    finally:
        conn.close()

    audit = dreaming_worker.run_dreaming_cycle()
    assert audit["status"] == "skipped"
    assert audit.get("reason") == "not_idle"


def test_run_cycle_skipped_when_lease_held(monkeypatch, isolated_short_term_db):
    monkeypatch.setenv("KURO_DREAMING_ENABLED", "true")
    assert memory_manager.acquire_dreaming_lease("dreaming", "other", 900) is True
    audit = dreaming_worker.run_dreaming_cycle(force=True)
    assert audit["status"] == "skipped"
    assert audit.get("reason") == "lease_held"


def test_run_cycle_ok_with_empty_corpus(monkeypatch, isolated_short_term_db):
    monkeypatch.setenv("KURO_DREAMING_ENABLED", "true")
    monkeypatch.setenv("KURO_CVE_SENTINEL_ENABLED", "false")
    audit = dreaming_worker.run_dreaming_cycle(force=True)
    # Empty corpus -> status ok, zero findings, audit row persisted.
    assert audit["status"] == "ok"
    assert audit["findings"] == 0

    import sqlite3
    conn = sqlite3.connect(isolated_short_term_db)
    try:
        row = conn.execute(
            "SELECT status, findings_count FROM dreaming_cycles WHERE id = ?",
            (audit["cycle_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "ok"
    assert row[1] == 0


def test_run_cycle_invokes_cve_sentinel(monkeypatch, isolated_short_term_db):
    """Smoke test: the Jarvis wave CVE sentinel hook runs inside
    run_dreaming_cycle and its counts are threaded into the audit dict."""
    monkeypatch.setenv("KURO_DREAMING_ENABLED", "true")
    monkeypatch.setenv("KURO_CVE_SENTINEL_ENABLED", "true")
    invoked = {"count": 0}

    def fake_cve_sentinel(*, cycle_id, dry_run):
        invoked["count"] += 1
        return {"cves": 3, "persisted": 3, "notified": 2}

    monkeypatch.setattr(dreaming_worker, "_run_cve_sentinel", fake_cve_sentinel)
    audit = dreaming_worker.run_dreaming_cycle(force=True, dry_run=True)
    assert invoked["count"] == 1
    assert audit["cve_findings"] == 3
    assert audit["cve_persisted"] == 3
    assert audit["cve_notified"] == 2
