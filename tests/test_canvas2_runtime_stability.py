"""Canvas 2 stability regression tests.

Focus:
- advisor_research_node remains sync-safe (no async loop dependency).
- metacognitive routing honors aggregate Canvas 2 runtime flag.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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

    def _launch_app(*args, **kwargs):
        return _FakePhoenixApp()

    fake_phoenix.launch_app = _launch_app
    sys.modules["phoenix"] = fake_phoenix

from kuro_backend import langgraph_core  # noqa: E402


def test_route_after_metacognitive_respects_canvas2_aggregate_flag(monkeypatch):
    monkeypatch.setattr(langgraph_core, "_CANVAS2_ANY_RUNTIME_ENABLED", True, raising=False)
    assert langgraph_core.route_after_metacognitive({}) == "strategic_planning_node"
    assert (
        langgraph_core.route_after_metacognitive({"next_step": "tool_node"})
        == "tool_node"
    )
    assert (
        langgraph_core.route_after_metacognitive({"metacognitive_flag": True})
        == "reflective_response_node"
    )


def test_advisor_research_node_sync_safe_and_persists_sources(monkeypatch):
    class _Resp:
        text = json.dumps(
            {"claims": ["c1"], "search_queries": ["test sovereign cognition"]}
        )

    class _Models:
        def generate_content(self, *args, **kwargs):
            return _Resp()

    class _Client:
        models = _Models()

    monkeypatch.setattr(langgraph_core, "_get_genai_client", lambda: _Client())

    from kuro_backend import intelligence_db, serper_tool

    monkeypatch.setattr(
        serper_tool,
        "serper_scholar",
        lambda query, num_results=5: [
            {
                "title": "Paper A",
                "link": "https://example.org/paper-a",
                "snippet": "scholar snippet",
                "year": 2026,
                "cited_by": 4,
            }
        ],
    )
    monkeypatch.setattr(
        serper_tool,
        "serper_news",
        lambda query, num_results=3: [
            {
                "title": "News A",
                "link": "https://example.org/news-a",
                "snippet": "news snippet",
                "date": "2026-05-08",
            }
        ],
    )

    saved = {"called": 0, "chat_id": None, "session_id": None, "username": None, "count": 0}

    def _fake_save_research_sources(session_id, username, chat_id, sources):
        saved["called"] += 1
        saved["session_id"] = session_id
        saved["username"] = username
        saved["chat_id"] = chat_id
        saved["count"] = len(sources or [])

    monkeypatch.setattr(intelligence_db, "save_research_sources", _fake_save_research_sources)

    state = {
        "persona_mode": "advisor",
        "_intent_category": "research",
        "user_input": "validasi framework sovereign cognition",
        "chat_id": "canvas2_sync_stability_chat",
        "_session_id": "canvas2_sync_stability_session",
        "username": "Pantronux",
    }
    result = langgraph_core.advisor_research_node(state)
    assert result["research_intent_detected"] is True
    assert "[RESEARCH_SOURCES" in result["research_sources_block"]
    assert "Scholar:" in result["research_sources_block"]
    assert saved["called"] == 1
    assert saved["session_id"] == "canvas2_sync_stability_session"
    assert saved["username"] == "Pantronux"
    assert saved["chat_id"] == "canvas2_sync_stability_chat"
    assert saved["count"] >= 1
