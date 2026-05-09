from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WORKING_DIR", str(PROJECT_ROOT))
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

from kuro_backend import langgraph_core


def _bridge_ctx() -> dict:
    return {
        "recent_messages": [],
        "memory_injection": "",
        "mem0_context_block": "",
        "referent_grounding_block": "",
        "ingestion_context_block": (
            "[INGESTION_KNOWLEDGE_CONTEXT]\n"
            "- Sumber 1: dokumen=ISO 27005; bagian=2; skor=0.93\n"
            "Risk treatment guidance"
        ),
        "ingestion_sources": [
            {
                "dataset_uuid": "ds_ok_1",
                "dataset_name": "ISO 27005",
                "chunk_index": 2,
                "chunk_id": 10,
                "score": 0.93,
                "chunk_text": "Risk treatment guidance",
            }
        ],
        "budget": None,
        "finance_block": "",
        "market_block": "",
    }


def test_response_node_injects_ingestion_and_fallback_citation(monkeypatch):
    captured = {}

    monkeypatch.setattr(langgraph_core, "_v7_reset_announcement_sent", True, raising=False)
    monkeypatch.setattr(langgraph_core, "get_system_instruction", lambda **kwargs: "SYS")
    monkeypatch.setattr(langgraph_core.memory_coordinator, "build_context_for_llm", lambda *args, **kwargs: _bridge_ctx())
    monkeypatch.setattr(langgraph_core.memory_coordinator, "build_gemini_contents_parts", lambda full_text, image_paths=None: [full_text])
    monkeypatch.setattr(langgraph_core.response_sanitizer, "sanitize_user_output", lambda text, fallback=None: text or (fallback or ""))
    monkeypatch.setattr(langgraph_core, "_persist_short_term_and_enqueue_writes", lambda *args, **kwargs: None)
    monkeypatch.setattr(langgraph_core.persona_runtime, "upsert_runtime_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(langgraph_core, "_EPISTEMIC_V2_ENABLED", False, raising=False)
    monkeypatch.setattr(langgraph_core.genai_types, "GenerateContentConfig", lambda **kwargs: kwargs)

    class _Resp:
        prompt_feedback = None
        usage_metadata = None
        text = "Jawaban ringkas tanpa referensi."

    class _Models:
        def generate_content(self, model, contents, config):
            captured["contents"] = contents
            captured["config"] = config
            return _Resp()

    class _Client:
        models = _Models()

    monkeypatch.setattr(langgraph_core, "_get_genai_client", lambda: _Client())

    state = {
        "user_input": "Jelaskan risk treatment",
        "username": "alice",
        "persona_mode": "consultant",
        "mem0_retrieved_memories": [],
        "tool_execution_result": {},
        "_session_id": "session-1",
        "chat_id": "chat-1",
        "message_count_before": 0,
    }

    result = langgraph_core.response_node(state)
    assert "[INGESTION_KNOWLEDGE_CONTEXT]" in captured["contents"][0]
    assert "bagian" in str(captured["config"].get("system_instruction", "")).lower()
    assert "berdasarkan dokumen iso 27005 pada bagian 2" in result["final_response"].lower()


def test_fastpath_stream_injects_ingestion_and_emits_fallback_citation(monkeypatch):
    captured = {"system_prompt": "", "full_message": ""}

    monkeypatch.setattr(langgraph_core, "_TRUE_TOKEN_STREAMING_ENABLED", True, raising=False)
    monkeypatch.setattr(langgraph_core, "_EPISTEMIC_V2_ENABLED", False, raising=False)
    monkeypatch.setattr(langgraph_core, "_STREAM_SANITIZER_ENABLED", False, raising=False)
    monkeypatch.setattr(langgraph_core, "_maybe_handle_pending_approval", lambda *args, **kwargs: None)
    monkeypatch.setattr(langgraph_core.memory_manager, "normalize_persona", lambda p: "consultant")
    monkeypatch.setattr(langgraph_core, "get_system_instruction", lambda **kwargs: "SYS")
    monkeypatch.setattr(langgraph_core.auth_db, "get_user", lambda username: {})
    monkeypatch.setattr(langgraph_core.memory_coordinator, "apply_path_tokens_to_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(langgraph_core.memory_coordinator, "maybe_trigger_chat_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(langgraph_core, "reflection_node", lambda state: {"_intent": "new"})
    monkeypatch.setattr(langgraph_core.response_sanitizer, "sanitize_user_output", lambda text, fallback=None: text or (fallback or ""))
    monkeypatch.setattr(langgraph_core, "_persist_short_term_and_enqueue_writes", lambda *args, **kwargs: None)
    monkeypatch.setattr(langgraph_core.persona_runtime, "upsert_runtime_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(langgraph_core, "_enqueue_post_response_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(langgraph_core.chat_history, "get_session_message_count", lambda chat_id: 0)

    async def _fake_build_ctx(*args, **kwargs):
        return _bridge_ctx()

    async def _fake_stream(system_prompt, full_message, persona_mode=None):
        captured["system_prompt"] = system_prompt
        captured["full_message"] = full_message
        yield "Jawaban fastpath tanpa sitasi."

    monkeypatch.setattr(langgraph_core.memory_coordinator, "build_context_for_llm_async", _fake_build_ctx)
    monkeypatch.setattr(langgraph_core, "_stream_direct_llm_chunks", _fake_stream)

    from kuro_backend import semantic_cache

    monkeypatch.setattr(semantic_cache, "lookup", lambda *args, **kwargs: None)
    monkeypatch.setattr(semantic_cache, "store", lambda *args, **kwargs: None)
    monkeypatch.setattr(semantic_cache, "classify_tags", lambda *args, **kwargs: [])

    async def _collect():
        chunks = []
        async for chunk in langgraph_core.process_chat_with_graph_stream(
            "Jelaskan risk treatment",
            persona_override="consultant",
            username="alice",
            chat_id="chat-2",
            session_id="session-2",
            stream_metrics={},
        ):
            chunks.append(chunk)
        return "".join(chunks)

    output = asyncio.run(_collect())

    assert "[INGESTION_KNOWLEDGE_CONTEXT]" in captured["full_message"]
    assert "bagian" in captured["system_prompt"].lower()
    assert "berdasarkan dokumen iso 27005 pada bagian 2" in output.lower()
