from __future__ import annotations

import sys
import types
import importlib.util
from types import SimpleNamespace


def _needs_langgraph_stub() -> bool:
    existing = sys.modules.get("langgraph")
    if existing is not None and not hasattr(existing, "__path__"):
        return True
    try:
        return importlib.util.find_spec("langgraph") is None
    except (ImportError, ValueError):
        return True


if _needs_langgraph_stub():
    fake_langgraph = types.ModuleType("langgraph")
    fake_langgraph.__path__ = []
    fake_checkpoint = types.ModuleType("langgraph.checkpoint")
    fake_checkpoint.__path__ = []
    fake_memory = types.ModuleType("langgraph.checkpoint.memory")

    class _FakeMemorySaver:
        pass

    class _FakeCompiledGraph:
        def invoke(self, *args, **kwargs):
            return {}

        def stream(self, *args, **kwargs):
            return iter(())

        def get_graph(self):
            return SimpleNamespace(nodes={}, edges=[])

    class _FakeStateGraph:
        def __init__(self, *args, **kwargs):
            pass

        def add_node(self, *args, **kwargs):
            return None

        def add_edge(self, *args, **kwargs):
            return None

        def add_conditional_edges(self, *args, **kwargs):
            return None

        def set_entry_point(self, *args, **kwargs):
            return None

        def compile(self, *args, **kwargs):
            return _FakeCompiledGraph()

    fake_memory.MemorySaver = _FakeMemorySaver
    fake_graph = types.ModuleType("langgraph.graph")
    fake_graph.StateGraph = _FakeStateGraph
    fake_graph.END = "__end__"
    fake_graph.START = "__start__"
    fake_graph.add_messages = lambda left, right: (left or []) + (right or [])
    sys.modules["langgraph"] = fake_langgraph
    sys.modules["langgraph.checkpoint"] = fake_checkpoint
    sys.modules["langgraph.checkpoint.memory"] = fake_memory
    sys.modules["langgraph.graph"] = fake_graph

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

import main


class _Service:
    def __init__(self, *, fail: bool = False):
        self.fail = fail

    def assert_api_enabled(self):
        return None

    def build_advisor_context(self, *, session_id: str, workflow_mode: str = "quick"):
        if self.fail:
            raise RuntimeError("missing playground session")
        return {
            "context_type": "playground_advisor_context",
            "session": {"session_id": session_id},
            "executions": [],
        }


def _app_with_service(service):
    return SimpleNamespace(state=SimpleNamespace(playground_service=service))


def test_advisor_context_block_skips_non_advisor_unlinked_disabled_and_missing(monkeypatch):
    monkeypatch.setattr(
        main.chat_history,
        "get_session",
        lambda chat_id, username=None: {"linked_playground_session_id": "pg-1"},
    )
    assert (
        main._build_playground_advisor_context_block(
            app_obj=_app_with_service(_Service()),
            persona="consultant",
            chat_id="chat-1",
            username="Pantronux",
        )
        == ""
    )

    monkeypatch.setattr(main.chat_history, "get_session", lambda chat_id, username=None: {})
    assert (
        main._build_playground_advisor_context_block(
            app_obj=_app_with_service(_Service()),
            persona="advisor",
            chat_id="chat-1",
            username="Pantronux",
        )
        == ""
    )

    monkeypatch.setattr(
        main.chat_history,
        "get_session",
        lambda chat_id, username=None: {"linked_playground_session_id": "pg-1"},
    )
    assert (
        main._build_playground_advisor_context_block(
            app_obj=_app_with_service(None),
            persona="advisor",
            chat_id="chat-1",
            username="Pantronux",
        )
        == ""
    )
    assert (
        main._build_playground_advisor_context_block(
            app_obj=_app_with_service(_Service(fail=True)),
            persona="advisor",
            chat_id="chat-1",
            username="Pantronux",
        )
        == ""
    )


def test_advisor_context_block_formats_compact_json(monkeypatch):
    monkeypatch.setattr(
        main.chat_history,
        "get_session",
        lambda chat_id, username=None: {"linked_playground_session_id": "pg-1"},
    )

    block = main._build_playground_advisor_context_block(
        app_obj=_app_with_service(_Service()),
        persona="advisor",
        chat_id="chat-1",
        username="Pantronux",
    )

    assert block.startswith("[PLAYGROUND_ADVISOR_CONTEXT]")
    assert "observable forensic artifacts only" in block
    assert "Do not claim" in block
    assert "hidden chain-of-thought" in block
    assert "private provider internals" in block
    assert '"context_type":"playground_advisor_context"' in block
