"""LangGraph topology contract tests.

--- Header Doc ---
Purpose: Validate compiled DAG topology exposure for core Kuro graph nodes.
Caller: pytest Batch-3 hardening gate.
Dependencies: kuro_backend.langgraph_core.export_graph_topology.
Main Functions: test_all_expected_nodes_present, test_graph_has_edges,
                test_memory_extraction_is_terminal_or_loops.
Side Effects: None.
"""
from __future__ import annotations

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

    fake_phoenix.launch_app = lambda *args, **kwargs: _FakePhoenixApp()
    sys.modules["phoenix"] = fake_phoenix

from kuro_backend.langgraph_core import export_graph_topology

EXPECTED_NODES = {
    "supervisor_node",
    "memory_retrieval_node",
    "retrieval_grader_node",
    "query_transform_node",
    "attention_filter_node",
    "advisor_research_node",
    "executive_monitor_node",
    "metacognitive_review_node",
    "response_node",
    "tool_node",
    "memory_extraction_node",
}


def test_all_expected_nodes_present():
    topology = export_graph_topology()
    missing = EXPECTED_NODES - set(topology["nodes"])
    assert not missing, f"Missing nodes from DAG: {missing}"


def test_graph_has_edges():
    topology = export_graph_topology()
    assert len(topology["edges"]) > 0, "Graph has no edges"


def test_memory_extraction_is_terminal_or_loops():
    topology = export_graph_topology()
    outgoing = [edge for edge in topology["edges"] if edge[0] == "memory_extraction_node"]
    assert len(outgoing) <= 1, (
        "memory_extraction_node has unexpected outgoing edges: "
        f"{outgoing}"
    )
