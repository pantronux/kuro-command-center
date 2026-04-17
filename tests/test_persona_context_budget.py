"""Tests for Persona-Aware Context Management (V5.5).

Covers:
  P1  - persona budgets sum to 1.0 and honour L3 floor
  P6  - token_budget.apply_persona_budget + L3 immutability under enforce_global_ceiling
  P2  - short_term_summaries.summary_json round-trip + research_ledger append
  P4  - novelty points / technical specs persist in research_ledger through eviction
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Minimal module stubs so this test can import without optional deps.
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


from kuro_backend import personas
from kuro_backend import token_budget


# ---------------------------------------------------------------------------
# P1 — per-persona budgets
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("persona", ["advisor", "tactical", "consultant", "butler", "chill"])
def test_context_budget_weights_sum_to_one(persona: str) -> None:
    budget = personas.get_context_budget(persona)
    total = (
        budget.weights.layer1_recent
        + budget.weights.layer2_semantic
        + budget.weights.layer3_factual
    )
    assert abs(total - 1.0) < 1e-3, f"{persona} weights must sum to 1.0, got {total}"


@pytest.mark.parametrize("persona", ["advisor", "tactical", "consultant", "butler", "chill"])
def test_context_budget_layer3_floor(persona: str) -> None:
    budget = personas.get_context_budget(persona)
    # Every persona must preserve at least 15% of its budget for SSoT.
    assert budget.weights.layer3_factual >= 0.15, (
        f"{persona} layer3_factual={budget.weights.layer3_factual} violates SSoT floor"
    )
    # Derived token counts must be positive.
    assert budget.layer1_tokens > 0
    assert budget.layer2_tokens > 0
    assert budget.layer3_tokens > 0
    assert budget.layer3_floor_tokens >= int(budget.layer3_tokens * 0.60) - 1


def test_context_budget_unknown_persona_falls_back() -> None:
    # normalize_persona_key falls back to 'consultant'.
    b = personas.get_context_budget("__bogus_persona__")
    assert b.persona == "consultant"


def test_context_budget_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KURO_BUDGET_ADVISOR", "12000")
    # Rebuild map (helper not exported — exercise via direct call).
    fresh = personas._build_budgets()  # type: ignore[attr-defined]
    assert fresh["advisor"].total_tokens == 12000


# ---------------------------------------------------------------------------
# P6 — token budget: persona-aware quotas + L3 immutability
# ---------------------------------------------------------------------------

def test_build_persona_section_quotas_partitions_layers() -> None:
    budget = personas.get_context_budget("advisor")
    quotas = token_budget.build_persona_section_quotas(budget)
    # Layer 1 section
    assert quotas["summary"] == budget.layer1_tokens
    # Layer 2 sections split adds up roughly to layer2_tokens
    l2 = quotas["memory_injection"] + quotas["mem0"] + quotas["referent"]
    assert abs(l2 - budget.layer2_tokens) <= 5
    # Layer 3 sections split adds up roughly to layer3_tokens
    l3 = quotas["habit"] + quotas["compliance"] + quotas["ssot_factual"]
    assert abs(l3 - budget.layer3_tokens) <= 5


def test_apply_persona_budget_respects_layer_quotas() -> None:
    budget = personas.get_context_budget("tactical")
    long_text = "x" * 50000  # definitely larger than any single quota
    sections = {
        "summary": long_text,
        "memory_injection": long_text,
        "mem0": long_text,
        "habit": long_text,
        "compliance": long_text,
    }
    out = token_budget.apply_persona_budget(sections, budget)
    for name, text in out.items():
        approx = token_budget.approx_tokens(text)
        quota = token_budget.build_persona_section_quotas(budget)[name]
        # Trimmer can leave head+tail with ellipsis; must not exceed quota by
        # more than a tiny rounding slack.
        assert approx <= quota + 10, f"{name} exceeded quota {approx}>{quota}"


def test_enforce_global_ceiling_protects_layer3_floor() -> None:
    budget = personas.get_context_budget("butler")  # L3-heavy persona
    l3_text = "FACT " * 5000  # large Layer 3 block
    l1_text = "turn " * 5000
    l2_text = "rag "  * 5000
    parts = [
        ("summary", l1_text),
        ("memory_injection", l2_text),
        ("habit", l3_text),
        ("compliance", l3_text),
    ]
    trimmed = token_budget.enforce_global_ceiling(parts, budget=budget)
    # Collect final L3 tokens post-trim
    l3_tokens_after = sum(
        token_budget.approx_tokens(t) for name, t in trimmed
        if name in ("habit", "compliance", "ssot_factual")
    )
    # SSoT floor must be respected even under aggressive overshoot
    # (sum of per-section floors is >= layer3_floor_tokens across 3 sections;
    # we only have 2 L3 sections here so compare against 2/3 of floor).
    min_expected = int(budget.layer3_floor_tokens * (2 / 3)) - 10
    assert l3_tokens_after >= min_expected, (
        f"Layer 3 trimmed below floor: {l3_tokens_after} < {min_expected}"
    )


def test_trim_priority_places_layer3_last() -> None:
    order = token_budget._TRIM_PRIORITY  # type: ignore[attr-defined]
    assert order[-3:] == ("habit", "compliance", "ssot_factual")


# ---------------------------------------------------------------------------
# P2 — summary_json + research_ledger durability
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_short_term_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Point memory_manager at an isolated SQLite DB for this test."""
    from kuro_backend import memory_manager

    db_path = tmp_path / "short_term.db"
    monkeypatch.setattr(memory_manager, "SHORT_TERM_DB", str(db_path))
    memory_manager.init_short_term_db()
    yield str(db_path)


def test_summary_json_roundtrip(temp_short_term_db: str) -> None:
    from kuro_backend import memory_manager

    summary = {
        "topic": "PhD forensic pipeline",
        "decisions": ["gunakan SHA-256 untuk chain-of-custody"],
        "entities": ["NIST AI 100-2", "EU AI Act"],
        "open_questions": ["bagaimana cara memverifikasi token inference?"],
        "novelty_points": ["adversarial forensics via token-level provenance"],
        "technical_specs": [],
        "compliance_refs": [],
        "tone_markers": [],
    }
    memory_manager.upsert_short_term_summary_json(
        "advisor", 42, summary, fallback_text="fallback text"
    )
    out = memory_manager.get_short_term_summary_json("advisor")
    assert out is not None
    assert out["last_entry_id"] == 42
    assert out["summary_json"]["topic"] == "PhD forensic pipeline"
    assert "adversarial forensics via token-level provenance" in (
        out["summary_json"]["novelty_points"]
    )


def test_research_ledger_append_and_query(temp_short_term_db: str) -> None:
    from kuro_backend import memory_manager

    rid = memory_manager.append_research_ledger(
        "advisor", "novelty_point",
        "adversarial forensics via token-level provenance",
        source_entry_id=101,
    )
    assert rid is not None and rid > 0

    # empty content is ignored
    assert memory_manager.append_research_ledger("advisor", "novelty_point", "") is None

    rows = memory_manager.query_research_ledger("advisor", kinds=["novelty_point"])
    assert len(rows) == 1
    assert rows[0]["content"].startswith("adversarial forensics")
    assert rows[0]["source_entry_id"] == 101


def test_research_ledger_batch_append(temp_short_term_db: str) -> None:
    from kuro_backend import memory_manager

    n = memory_manager.append_research_ledger_batch(
        "tactical",
        [
            {"kind": "technical_spec", "content": "python 3.10+"},
            {"kind": "technical_spec", "content": "uvicorn --host 0.0.0.0"},
            {"kind": "decision", "content": "switch to Poetry"},
            {"kind": "decision", "content": ""},  # skipped
        ],
        source_entry_id=7,
    )
    assert n == 3
    specs = memory_manager.query_research_ledger(
        "tactical", kinds=["technical_spec"]
    )
    assert len(specs) == 2
    assert all(r["source_entry_id"] == 7 for r in specs)


# ---------------------------------------------------------------------------
# P4 — novelty / specs survive even when the JSON cache is overwritten
# ---------------------------------------------------------------------------

def test_novelty_points_persist_through_summary_overwrite(temp_short_term_db: str) -> None:
    from kuro_backend import memory_coordinator
    from kuro_backend import memory_manager

    # Simulate first summarization extracting 2 novelty points
    first = {
        "topic": "Forensic chain-of-custody",
        "decisions": ["baseline hashing"],
        "entities": ["NIST AI 100-2"],
        "open_questions": [],
        "novelty_points": [
            "token-level inference provenance",
            "memory volatility forensics",
        ],
        "technical_specs": [],
        "compliance_refs": [],
        "tone_markers": [],
    }
    memory_manager.upsert_short_term_summary_json(
        "advisor", 10, first, fallback_text="f1"
    )
    memory_coordinator._persist_summary_to_ledger(  # type: ignore[attr-defined]
        "advisor", first, source_entry_id=10,
    )

    # Second summarization replaces cached summary entirely (eviction path)
    second = {
        "topic": "Different topic",
        "decisions": [],
        "entities": [],
        "open_questions": [],
        "novelty_points": [],
        "technical_specs": [],
        "compliance_refs": [],
        "tone_markers": [],
    }
    memory_manager.upsert_short_term_summary_json(
        "advisor", 22, second, fallback_text="f2"
    )

    # Cached JSON is gone, but ledger keeps both novelty points forever.
    cached = memory_manager.get_short_term_summary_json("advisor")
    assert cached is not None
    assert cached["summary_json"]["novelty_points"] == []

    ledger = memory_manager.query_research_ledger("advisor", kinds=["novelty_point"])
    contents = {r["content"] for r in ledger}
    assert "token-level inference provenance" in contents
    assert "memory volatility forensics" in contents


def test_render_summary_frontloads_novelty_for_advisor() -> None:
    from kuro_backend import memory_coordinator

    summary = {
        "topic": "Forensic AI evaluation",
        "decisions": ["use TPR/FPR"],
        "entities": ["LIME", "SHAP"],
        "open_questions": ["what about out-of-distribution inputs?"],
        "novelty_points": [
            "token-level provenance SHA-chain",
            "inference volatility metric",
        ],
        "technical_specs": [],
        "compliance_refs": [],
        "tone_markers": [],
    }
    rendered = memory_coordinator.render_summary_for_prompt(summary, "advisor")
    # Novelty Points section must appear BEFORE Decisions / Entities
    assert "Novelty Points" in rendered
    np_idx = rendered.index("Novelty Points")
    dec_idx = rendered.index("Keputusan")
    ent_idx = rendered.index("Entitas")
    assert np_idx < dec_idx < ent_idx


def test_render_summary_frontloads_specs_for_tactical() -> None:
    from kuro_backend import memory_coordinator

    summary = {
        "topic": "Prod debug",
        "decisions": ["roll back to v5.4"],
        "entities": ["nginx"],
        "open_questions": [],
        "novelty_points": [],
        "technical_specs": ["NGINX 1.25", "port 8443", "/var/log/kuro.log"],
        "compliance_refs": [],
        "tone_markers": [],
    }
    rendered = memory_coordinator.render_summary_for_prompt(summary, "tactical")
    assert "Technical Specs" in rendered
    ts_idx = rendered.index("Technical Specs")
    dec_idx = rendered.index("Keputusan")
    assert ts_idx < dec_idx


# ---------------------------------------------------------------------------
# Schema migration on a legacy DB (no summary_json column, no research_ledger)
# ---------------------------------------------------------------------------

def test_init_db_migrates_legacy_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from kuro_backend import memory_manager

    db_path = tmp_path / "legacy.db"
    # Hand-craft a legacy DB that only has the old summary column.
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE short_term (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            persona_scope TEXT NOT NULL DEFAULT 'consultant',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE short_term_summaries (
            persona_scope TEXT PRIMARY KEY,
            last_entry_id INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT '',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO short_term_summaries (persona_scope, last_entry_id, summary)
        VALUES ('advisor', 3, 'legacy prose summary');
    """)
    conn.commit()
    conn.close()

    monkeypatch.setattr(memory_manager, "SHORT_TERM_DB", str(db_path))
    memory_manager.init_short_term_db()  # must add summary_json + research_ledger

    out = memory_manager.get_short_term_summary_json("advisor")
    assert out is not None
    # Legacy prose must surface via _legacy_text fallback.
    assert out["summary_json"].get("_legacy_text") == "legacy prose summary"

    # research_ledger table should now exist.
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='research_ledger'"
    )
    assert cur.fetchone() is not None
    conn.close()
