"""Tests for deictic / attachment grounding in memory_coordinator.

--- Header Doc ---
Purpose: Verify anaphora anchors (ini/itu/tadi) route through explicit grounding block.
Covers: memory_coordinator.build_referent_grounding_block + apply_path_tokens_to_runtime.
Fixtures: Synthetic turn state + tmp files.
"""
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

from kuro_backend import memory_coordinator


def test_format_same_turn_attachment_index_orders_files():
    block = memory_coordinator.format_same_turn_attachment_index(
        [
            {"type": "image", "stored_filename": "a_20260101.png", "original_filename": "a.png"},
            {"type": "image", "stored_filename": "b_20260101.png", "original_filename": "b.png"},
        ]
    )
    assert "[ATTACHMENT_ORDER_THIS_REQUEST]" in block
    assert "1. type=image" in block
    assert "a_20260101.png" in block
    assert "2. type=image" in block
    assert "b_20260101.png" in block


def test_build_referent_grounding_block_with_deictic(monkeypatch):
    fake_hist = [
        {"role": "user", "content": "hai", "attachments": []},
        {
            "role": "user",
            "content": "lihat ini",
            "attachments": ["vlc_20260101_120000.png", "vlc_test_20260101_120001.jpg"],
        },
        {"role": "assistant", "content": "ok", "attachments": []},
    ]

    def _gh(*args, **kwargs):
        return list(fake_hist)

    monkeypatch.setattr("kuro_backend.chat_history.get_history", _gh)

    block = memory_coordinator.build_referent_grounding_block(
        "Apa isi gambar ini?",
        "consultant",
    )
    assert block is not None
    assert "[RECENT_ATTACHMENTS_GROUNDING]" in block
    assert "vlc_20260101_120000.png" in block
    assert "vlc_test_20260101_120001.jpg" in block


def test_build_referent_grounding_block_skips_when_no_signal(monkeypatch):
    def _gh(*args, **kwargs):
        return [{"role": "user", "content": "hello", "attachments": []}]

    monkeypatch.setattr("kuro_backend.chat_history.get_history", _gh)

    block = memory_coordinator.build_referent_grounding_block(
        "What is ISO 27001?",
        "consultant",
    )
    assert block is None


def test_build_context_includes_referent_when_deictic(monkeypatch):
    def _gh(*args, **kwargs):
        return [
            {
                "role": "user",
                "content": "upload",
                "attachments": ["x.png"],
            },
        ]

    monkeypatch.setattr("kuro_backend.chat_history.get_history", _gh)

    def _stub_query_memory(*args, **kwargs):
        return {"short_term": "", "long_term": "", "profile": ""}

    def _stub_format(mem):
        return ""

    monkeypatch.setattr("kuro_backend.memory_manager.query_memory", _stub_query_memory)
    monkeypatch.setattr(
        "kuro_backend.memory_manager.format_memory_with_temporal_grounding", _stub_format
    )
    monkeypatch.setattr("kuro_backend.memory_manager.get_short_term", lambda **kw: [])

    ctx = memory_coordinator.build_context_for_llm(
        "jelaskan itu",
        "consultant",
        include_referent_grounding=True,
    )
    assert ctx.get("referent_grounding_block")
    assert "x.png" in ctx["referent_grounding_block"]
