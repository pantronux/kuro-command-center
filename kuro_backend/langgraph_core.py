"""
Kuro AI V6.0 Sovereign - LangGraph Core (Guardrails Removed) [2026-04-17]
================================================================================
AI Core with LangGraph Stateful Architecture for Agentik Long-Term Reasoning
SDK: google-genai v3 Protocol with LangGraph State Machine
V5.5: Guardrails REMOVED for maximum performance. Local + VPN + Auth environment.
      Latency optimized: direct path from memory retrieval to response generation.

--- Header Doc ---
Purpose: Primary stateful reasoning pipeline (supervisor -> tool_node -> response_node) backing /api/chat.
Caller: main.py chat routes, stream fastpath, services/core_service orchestration.
Dependencies: google-genai, langgraph, personas, memory_coordinator, token_budget, tools.base_tools, observability, semantic_cache.
Main Functions: build_graph(), run_turn(), stream_turn(), supervisor_node, tool_node, response_node.
Side Effects: LLM API calls (Gemini), SQLite reads via memory/finance/intelligence, ChromaDB reads, token-usage metrics, semantic-cache writes, threading primitives for fastpath.
"""
import asyncio
import functools
import hashlib
import json
import logging
import os
import queue
import re
import secrets
import threading
import time
import uuid
from datetime import datetime
from typing import Annotated, Any, AsyncGenerator, Dict, Iterator, List, Optional, TypedDict

from google import genai
from google.genai import types as genai_types

# LangGraph imports
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

# Kuro imports
from kuro_backend import (
    chat_history,
    memory_coordinator,
    memory_manager,
    observability,
    perpetual_memory,
)
from kuro_backend import tools as kuro_tools
from kuro_backend.config import PRIMARY_MODEL, settings

from kuro_backend import personas, token_budget
from kuro_backend.personas import build_system_instruction

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

DESTRUCTIVE_KEYWORDS = [
    "delete",
    "hapus",
    "format",
    "rm -rf",
    "rm ",
    "truncate",
    "shutdown",
    "reboot",
    "overwrite",
    "drop table",
]
OPENCLAW_READONLY_KEYWORDS = [
    "search",
    "web search",
    "paper",
    "novelty",
    "novelty check",
    "analisis",
    "analyze",
    "metadata",
    "log",
    "forensic",
    "mapping",
    "uu pdp",
    "eu ai act",
    "nist",
    "iso",
]
_approval_lock = threading.Lock()
_pending_tool_approval: Dict[str, Dict[str, Any]] = {}
_post_response_worker_started = False
_v7_reset_announcement_sent = False
_v7_reset_announcement_lock = threading.Lock()
_TRUE_TOKEN_STREAMING_ENABLED = (
    os.getenv("KURO_TRUE_TOKEN_STREAMING", "1").strip().lower() in {"1", "true", "yes", "on"}
)
_POST_RESPONSE_QUEUE_MAXSIZE = int(os.getenv("KURO_POST_RESPONSE_QUEUE_MAXSIZE", "500"))
_post_response_queue = queue.Queue(maxsize=_POST_RESPONSE_QUEUE_MAXSIZE)  # type: ignore[assignment]
_DEBUG_LOG_PATH = "/home/kuro/projects/kuro/.cursor/debug-0dd1b5.log"


@functools.lru_cache(maxsize=1)
def _get_genai_client() -> "genai.Client":
    """Single shared google-genai client (lazy init, thread-safe via lru_cache)."""
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def _parse_approval_token(user_input: str) -> Optional[str]:
    text = (user_input or "").strip().lower()
    if text.startswith("approve "):
        parts = text.split(maxsplit=1)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip()
    return None


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: Dict[str, Any]) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "0dd1b5",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion


def _contains_destructive_keyword(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in DESTRUCTIVE_KEYWORDS)


def _set_pending_approval(
    scope_key: str,
    tool_name: str,
    args: Dict[str, Any],
    reason: str,
    trace_id: str = "",
) -> str:
    nonce = secrets.token_hex(4)
    payload_hash = hashlib.sha256(
        json.dumps({"tool": tool_name, "args": args}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    with _approval_lock:
        _pending_tool_approval[scope_key] = {
            "tool": tool_name,
            "args": args,
            "reason": reason,
            "created_at": datetime.now().isoformat(),
            "nonce": nonce,
            "payload_hash": payload_hash,
            "expires_at": (datetime.now().timestamp() + 600.0),
            "trace_id": trace_id,
        }
    logger.info(
        "[HITL_AUDIT] requested trace_id=%s scope=%s tool=%s nonce=%s payload_hash=%s",
        trace_id,
        scope_key,
        tool_name,
        nonce,
        payload_hash,
    )
    return nonce


def _get_pending_approval(scope_key: str) -> Optional[Dict[str, Any]]:
    with _approval_lock:
        pending = _pending_tool_approval.get(scope_key)
        if not pending:
            return None
        if pending.get("expires_at", 0.0) < datetime.now().timestamp():
            _pending_tool_approval.pop(scope_key, None)
            return None
        return dict(pending)


def _clear_pending_approval(scope_key: str) -> None:
    with _approval_lock:
        pending = _pending_tool_approval.pop(scope_key, None)
    if pending:
        logger.info(
            "[HITL_AUDIT] cleared trace_id=%s scope=%s tool=%s nonce=%s",
            pending.get("trace_id", ""),
            scope_key,
            pending.get("tool"),
            pending.get("nonce"),
        )


def _render_pending_approval_message(pending: Dict[str, Any]) -> str:
    tool_name = pending.get("tool", "unknown_tool")
    reason = pending.get("reason", "Aksi berisiko terdeteksi.")
    return (
        "[HITL APPROVAL REQUIRED]\n"
        f"{reason}\n"
        f"Tool `{tool_name}` belum dieksekusi.\n"
        f"Ketik 'approve {pending.get('nonce', '')}' untuk lanjut, atau perintah lain untuk batal."
    )


def _maybe_handle_pending_approval(user_input: str, scope_key: str) -> Optional[str]:
    pending = _get_pending_approval(scope_key)
    if not pending:
        return None

    token = _parse_approval_token(user_input)
    if not token:
        cancel_token = (user_input or "").strip().lower()
        if cancel_token in {"cancel", "batal", "no", "n", "tidak"}:
            logger.info(
                "[HITL_AUDIT] cancelled trace_id=%s scope=%s tool=%s",
                pending.get("trace_id", ""),
                scope_key,
                pending.get("tool"),
            )
            _clear_pending_approval(scope_key)
            return "Approval dibatalkan. Tool tidak dieksekusi."
        return _render_pending_approval_message(pending)
    if token != str(pending.get("nonce", "")):
        logger.warning(
            "[HITL_AUDIT] approval token mismatch trace_id=%s scope=%s token=%s",
            pending.get("trace_id", ""),
            scope_key,
            token,
        )
        return _render_pending_approval_message(pending)

    expected_hash = str(pending.get("payload_hash", ""))
    actual_hash = hashlib.sha256(
        json.dumps(
            {"tool": pending.get("tool"), "args": pending.get("args", {})},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if expected_hash and expected_hash != actual_hash:
        logger.error(
            "[HITL_AUDIT] payload hash mismatch trace_id=%s scope=%s expected=%s actual=%s",
            pending.get("trace_id", ""),
            scope_key,
            expected_hash,
            actual_hash,
        )
        _clear_pending_approval(scope_key)
        return "Approval ditolak karena payload berubah. Silakan kirim ulang instruksi."

    tool_name = pending.get("tool")
    args = pending.get("args", {})
    try:
        tool_result = _execute_tool(tool_name, args)
    finally:
        _clear_pending_approval(scope_key)
    logger.info(
        "[HITL_AUDIT] executed trace_id=%s scope=%s tool=%s status=%s",
        pending.get("trace_id", ""),
        scope_key,
        tool_name,
        tool_result.get("status"),
    )

    if tool_result.get("status") == "success":
        return (
            "Approval nonce diterima. "
            f"Tool `{tool_name}` berhasil dieksekusi.\nHasil: {tool_result.get('result')}"
        )
    return (
        f"Approval nonce diterima, tetapi eksekusi `{tool_name}` gagal: "
        f"{tool_result.get('message', 'unknown error')}"
    )


def _execute_post_response_task(task: Dict[str, Any]) -> None:
    """Dispatch a single post-response task to memory_coordinator."""
    kind = task.get("kind")
    if kind == "memory_write":
        user_input = task.get("user_input", "")
        final_response = task.get("final_response", "")
        persona_scope = task.get("persona_scope") or memory_manager.get_active_persona()
        memory_coordinator.execute_memory_write_task(user_input, final_response, persona_scope)
    elif kind == "mem0_extract":
        user_input = task.get("user_input", "")
        final_response = task.get("final_response", "")
        memory_coordinator.execute_mem0_extract_task(user_input, final_response)
    else:
        logger.warning("[POST_RESPONSE_WORKER] Unknown task kind=%s", kind)


def _post_response_worker_loop() -> None:
    while True:
        task = _post_response_queue.get()
        kind = task.get("kind", "unknown")
        try:
            try:
                _execute_post_response_task(task)
            except Exception as first_exc:
                logger.warning(
                    "[POST_RESPONSE_WORKER] Task failed kind=%s error=%s (retrying once)",
                    kind,
                    first_exc,
                )
                time.sleep(0.5)
                _execute_post_response_task(task)
        except Exception as exc:
            logger.error(
                "[POST_RESPONSE_WORKER] Task dropped kind=%s error=%s",
                kind,
                exc,
            )
        finally:
            _post_response_queue.task_done()


def _start_post_response_worker_once() -> None:
    global _post_response_worker_started
    if _post_response_worker_started:
        return
    worker = threading.Thread(
        target=_post_response_worker_loop,
        daemon=True,
        name="kuro-post-response-worker",
    )
    worker.start()
    _post_response_worker_started = True


def _enqueue_post_response_task(task: Dict[str, Any]) -> None:
    _start_post_response_worker_once()
    try:
        _post_response_queue.put_nowait(task)
    except queue.Full:
        logger.warning(
            "[POST_RESPONSE_WORKER] Queue full (size=%s); dropping task kind=%s",
            _post_response_queue.qsize(),
            task.get("kind", "unknown"),
        )


def get_post_response_queue_depth() -> int:
    """Observability helper — queue depth for health-check endpoints."""
    return _post_response_queue.qsize()


def _persist_short_term_and_enqueue_writes(user_input: str, response_text: str, persona_mode: str) -> None:
    memory_manager.add_short_term("user", user_input, persona_scope=persona_mode)
    memory_manager.add_short_term("assistant", response_text, persona_scope=persona_mode)


async def _stream_direct_llm_chunks(
    system_prompt: str,
    full_message: str,
    *,
    persona_mode: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Real token streaming bridge from blocking Gemini iterator into async generator.
    """
    loop = asyncio.get_running_loop()
    chunk_queue: asyncio.Queue = asyncio.Queue()
    profile = personas.get_sampling_profile(persona_mode)

    def _worker() -> None:
        try:
            client = _get_genai_client()
            stream = client.models.generate_content_stream(
                model=PRIMARY_MODEL,
                contents=full_message,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=profile.temperature,
                    top_p=profile.top_p,
                    top_k=profile.top_k,
                ),
            )
            for event in stream:
                chunk = getattr(event, "text", None)
                if chunk:
                    loop.call_soon_threadsafe(chunk_queue.put_nowait, ("chunk", str(chunk)))
            loop.call_soon_threadsafe(chunk_queue.put_nowait, ("done", None))
        except Exception as exc:
            loop.call_soon_threadsafe(chunk_queue.put_nowait, ("error", str(exc)))

    threading.Thread(target=_worker, daemon=True).start()

    while True:
        kind, payload = await chunk_queue.get()
        if kind == "chunk":
            yield payload
        elif kind == "done":
            return
        else:
            raise RuntimeError(payload or "direct token stream failed")

# ============================================
# AGENT STATE DEFINITION (The Memory)
# ============================================

class KuroState(TypedDict):
    """
    Kuro Agent State - persists across graph nodes.
    V5.5: Guardrail-related fields removed for performance.
    
    Fields:
    - messages: Conversation history (list of dicts with role/content)
    - next_step: Next node to route to (supervisor decision)
    - user_input: Original user message
    - final_response: Generated response to return
    - persona_mode: Current active persona
    - mem0_retrieved_memories: Memories retrieved from Mem0 for context
    - tool_execution_result: Result from tool execution (ToolNode output)
    - requires_approval: Flag for HITL interrupt (file operations need approval)
    """
    messages: Annotated[List[Dict], lambda x, y: x + y]
    next_step: str
    user_input: str
    final_response: str
    persona_mode: str
    image_paths: Optional[List[str]]
    mem0_retrieved_memories: List[Dict]
    tool_execution_result: Optional[Dict]
    requires_approval: bool
    _approval_scope: str
    _trace_id: str
    _intent: str


# ============================================
# PERSONA SYSTEM (shared with core.py via kuro_backend.personas)
# ============================================


def get_system_instruction(persona_override: Optional[str] = None) -> str:
    """Get system instruction with current time and active persona (graph variant)."""
    current_time = settings.get_current_time_formatted()
    current_date = settings.get_current_time().strftime("%Y-%m-%d")
    active_persona = memory_manager.normalize_persona(
        persona_override or memory_manager.get_active_persona()
    )
    return build_system_instruction(
        active_persona,
        current_time=current_time,
        current_date=current_date,
        kuro_version_label="V5.5 LangGraph",
        variant="graph",
    )

# ============================================
# NODE: REFLECTION (Task Continuity)
# ============================================

def reflection_node(state: KuroState) -> Dict[str, Any]:
    user_input = state.get("user_input", "").lower()
    edit_keywords = ["edit", "add", "revise", "revisi", "tambah", "ubah", "perbaiki", "lanjut", "sekali lagi", "update"]
    intent = "new"
    if any(kw in user_input for kw in edit_keywords):
        intent = "edit"
        logger.info("[REFLECTION] Intent detected as Edit/Update")
    return {"_intent": intent}


# ============================================
# NODE: SUPERVISOR (The Brain)
# ============================================

def supervisor_node(state: KuroState) -> Dict[str, Any]:
    """
    Supervisor Node: Analyzes user input and decides which node to route to.
    
    Routing Logic:
    - If query mentions file actions (buat, generate, excel, export) -> route to tool_node
    - If query is general conversation -> route directly to response_node
    """
    user_input = state.get("user_input", "").lower()
    
    # Observability tracing
    session_id = state.get("_session_id", "unknown")
    trace_attrs = observability.create_session_context(session_id=session_id)
    trace_attrs = observability.add_client_label(trace_attrs, user_input)
    
    with observability.trace_node("supervisor_node", trace_attrs) as span:
        # P1.2 — kick off Mem0 retrieve in parallel with the supervisor's
        # routing logic; memory_retrieval_node will await the future.
        try:
            memory_coordinator.prefetch_mem0(session_id, state.get("user_input", ""), limit=5)
        except Exception as exc:
            logger.debug("[SUPERVISOR] mem0 prefetch skipped: %s", exc)

        # Tool action keywords detection (strict): only explicit file/tool operations.
        # Avoid broad creators like "buatkan/generate/report" which are common
        # in normal chat requests and can misroute to tool_node.
        tool_keywords = [
            "export",
            "eksport",
            "excel",
            "spreadsheet",
            "template file",
            "list file",
            "daftar file",
            "simpan file",
            "save file",
            "delete file",
            "hapus file",
            "manage file",
            "buat file",
        ]

        # Chancellor / finances — route to tool_node for ledger tools
        finance_keywords = [
            "budget", "subscription", "subscriptions", "recurring expense",
            "recurring expenses", "monthly bill", "api spend", "api cost",
            "api usage", "monthly allocation", "ledger",
        ]
        market_keywords = [
            "stock", "stocks", "ticker", "share price", "nasdaq", "nyse",
            "portfolio", "equity", "equities", "nvda", "aapl", "msft",
            "prediction market", "polymarket", "metaculus", "odds", "probability",
            "earnings", "bullish", "bearish", "hedge",
        ]
        
        # Check for tool action query
        is_tool_query = any(kw in user_input for kw in tool_keywords)
        is_finance_query = any(kw in user_input for kw in finance_keywords)
        is_market_query = any(kw in user_input for kw in market_keywords)
        # #region agent log
        _debug_log(
            state.get("_trace_id", "") or state.get("_session_id", "unknown"),
            "H1",
            "langgraph_core.py:supervisor_node",
            "routing_signals",
            {
                "is_tool_query": is_tool_query,
                "is_finance_query": is_finance_query,
                "is_market_query": is_market_query,
                "input_preview": user_input[:160],
            },
        )
        # #endregion
        
        # Route to tool node for file actions
        if is_tool_query:
            logger.info("[SUPERVISOR] Routing to tool_node (file action detected)")
            if span:
                span.set_attribute("supervisor_node.decision", "tool_node")
            return {"next_step": "tool_node"}
        
        if is_finance_query or is_market_query:
            logger.info(
                "[SUPERVISOR] Routing to tool_node (finance=%s market=%s)",
                is_finance_query,
                is_market_query,
            )
            if span:
                span.set_attribute("supervisor_node.decision", "tool_node_finance")
            return {"next_step": "tool_node"}
        
        # Default: route to response generator
        logger.info("[SUPERVISOR] Routing to response_node (general query)")
        if span:
            span.set_attribute("supervisor_node.decision", "response_node")
        return {"next_step": "response_node"}


# ============================================
# NODE: MEMORY RETRIEVAL (Mem0)
# ============================================

def memory_retrieval_node(state: KuroState) -> Dict[str, Any]:
    if not isinstance(state, dict):
        logger.error("[MEM0] Invalid state type: %s", type(state))
        return {"mem0_retrieved_memories": []}

    user_input = state.get("user_input", "")
    session_id = state.get("_session_id", "")

    with observability.trace_node("memory_retrieval_node") as span:
        try:
            # P1.2 — consume supervisor's prefetch if present; otherwise fall
            # back to a live retrieval. Either path degrades gracefully.
            raw_memories = memory_coordinator.take_prefetched_mem0(session_id)
            if raw_memories is None:
                raw_memories = memory_coordinator.safe_mem0_retrieve(user_input, limit=5)

            if not isinstance(raw_memories, list):
                logger.warning("[MEM0] Unexpected output format: %s", type(raw_memories))
                processed_memories: List[Dict[str, Any]] = []
            else:
                processed_memories = [m for m in raw_memories if isinstance(m, dict)]

            if span is not None:
                span.set_attribute("mem0.ok", True)
                span.set_attribute("mem0.result_count", len(processed_memories))
            return {"mem0_retrieved_memories": processed_memories}

        except Exception as e:
            logger.error("[MEM0_RETRIEVAL] Critical Failure: %s", e)
            if span is not None:
                span.set_attribute("mem0.ok", False)
                try:
                    span.record_exception(e)
                except Exception:
                    pass
            return {"mem0_retrieved_memories": []}


# ============================================
# NODE: MEMORY EXTRACTION (Mem0)
# ============================================

def memory_extraction_node(state: KuroState) -> Dict[str, Any]:
    user_input = state.get("user_input", "")
    final_response = state.get("final_response", "")
    tool_result = state.get("tool_execution_result", {})

    # 1. Guard Clause: Jangan jalankan ekstraksi jika respon asisten kosong
    # Ini mencegah penyimpanan memori yang tidak lengkap atau error API
    if not final_response or len(final_response.strip()) == 0:
        logger.warning("[MEM0_EXTRACTION] Skipped: No final_response found in state.")
        return {}

    task_success = False
    if tool_result.get("status") == "success":
        task_success = True
    
    success_keywords = ["thanks", "terima kasih", "selesai", "fixed", "done", "berhasil", "sip", "ok", "confirmed"]
    if any(kw in user_input.lower() for kw in success_keywords):
        task_success = True

    if task_success:
        with observability.trace_node("memory_extraction_node"):
            _enqueue_post_response_task(
                {
                    "kind": "mem0_extract",
                    "user_input": user_input,
                    "final_response": final_response,
                }
            )
    else:
        logger.info("[MEM0_EXTRACTION] Skipped: Task not explicitly completed.")
    return {}


# ============================================
# NODE: RESPONSE GENERATOR (Final Answer - No Guardrails)
# ============================================

def response_node(state: KuroState) -> Dict[str, Any]:
    """
    Response Generator Node: Synthesizes all state data into final response.
    V5.5: Guardrails validation removed. Direct LLM response is returned.
    """
    user_input = state.get("user_input", "")
    persona_mode = memory_manager.normalize_persona(
        state.get("persona_mode", memory_manager.get_active_persona())
    )
    image_paths = state.get("image_paths")
    mem0_memories = state.get("mem0_retrieved_memories", [])
    tool_result = state.get("tool_execution_result", {})
    session_id = state.get("_session_id", "unknown")
    
    # Observability tracing
    trace_attrs = observability.create_session_context(session_id=session_id)
    trace_attrs = observability.add_client_label(trace_attrs, user_input)
    
    with observability.trace_node("response_node", trace_attrs) as span:
        memory_coordinator.apply_path_tokens_to_runtime(user_input, persona_mode)
        ctx = memory_coordinator.build_context_for_llm(
            user_input,
            persona_mode,
            mem0_retrieved_memories=mem0_memories or None,
        )
        memory_injection = ctx["memory_injection"]
        mem0_context_block = ctx.get("mem0_context_block")
        referent_block = ctx.get("referent_grounding_block")
        context_budget = ctx.get("budget")

        # Build system prompt
        system_prompt = get_system_instruction(persona_override=persona_mode)
        
        intent = state.get("_intent", "new")
        if intent == "edit":
            system_prompt += (
                "\n\n[TASK CONTINUITY LOCK]\n"
                "The Master is editing, revising, or adding to the previous turn. "
                "You MUST act as an incremental update to the existing state. "
                "DO NOT generate a 'New Conclusion' or restart the thought process. "
                "Maintain the exact same context and only apply the requested delta."
            )

        # Assemble per-section context blocks so we can apply the token budget
        # uniformly. Each block is independently trimmed to its quota before
        # concatenation, with a final global ceiling enforcement pass.
        sections: dict[str, str] = {}

        if referent_block:
            sections["referent"] = "\n\n" + referent_block

        if mem0_context_block:
            sections["mem0"] = f"\n\n[USER_CONTEXT - PERPETUAL MEMORY]\n{mem0_context_block}"
            logger.info("[MEM0] Injected %s memories into context", len(mem0_memories or []))

        if memory_injection:
            sections["memory_injection"] = memory_injection

        finance_block = (ctx or {}).get("finance_block") or ""
        if finance_block:
            sections["finance"] = "\n\n" + finance_block
        market_block = (ctx or {}).get("market_block") or ""
        if market_block:
            sections["market"] = "\n\n" + market_block

        tool_status = (tool_result or {}).get("status")
        if tool_status == "success":
            sections["tool_result"] = (
                "\n\n[TOOL EXECUTION RESULT]\n"
                f"Tool: {tool_result.get('tool', 'unknown')}\n"
                f"Result: {tool_result.get('result', '')}\n\n"
                "Please inform the user about the successful tool execution in a professional manner."
            )
        elif tool_status == "pending_approval":
            sections["tool_result"] = (
                "\n\n[HITL APPROVAL REQUIRED]\n"
                f"{tool_result.get('message', 'Approval needed for tool execution.')}\n\n"
                "Ask user to reply exactly with `approve <nonce>` to proceed."
            )
        elif tool_status == "error":
            sections["tool_result"] = (
                "\n\n[TOOL ERROR]\n"
                f"Error: {tool_result.get('message', 'Unknown error')}\n\n"
                "Inform the user about the error professionally."
            )
        # tool_status == "no_tool" or None -> proceed normally

        if context_budget is not None:
            budgeted = token_budget.apply_persona_budget(sections, context_budget)
        else:
            budgeted = token_budget.apply_section_budget(sections)
        ordered_names = (
            "referent",
            "mem0",
            "memory_injection",
            "finance",
            "market",
            "tool_result",
        )
        ordered_parts: list[tuple[str, str]] = [
            (name, budgeted[name]) for name in ordered_names if budgeted.get(name)
        ]
        ordered_parts = token_budget.collapse_duplicate_blocks(ordered_parts)
        ordered_parts = token_budget.enforce_global_ceiling(
            ordered_parts, budget=context_budget,
        )

        message_parts: list[str] = [user_input]
        message_parts.extend(text for _, text in ordered_parts)

        full_message = "\n".join(message_parts)
        contents_parts = memory_coordinator.build_gemini_contents_parts(
            full_message, image_paths if image_paths else None
        )
        # #region agent log
        _debug_log(
            state.get("_trace_id", "") or state.get("_session_id", "unknown"),
            "H6",
            "langgraph_core.py:response_node",
            "prompt_assembly_stats",
            {
                "full_message_chars": len(full_message),
                "sections_present": sorted([k for k, v in sections.items() if v]),
                "image_parts_count": len(image_paths or []),
            },
        )
        # #endregion

        # Generate response using direct google-genai SDK (more reliable)
        response_text: Optional[str] = None  # Initialize to detect if generation fails
        try:
            genai_client = _get_genai_client()

            profile = personas.get_sampling_profile(persona_mode)
            response = genai_client.models.generate_content(
                model=PRIMARY_MODEL,
                contents=contents_parts,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=profile.temperature,
                    top_p=profile.top_p,
                    top_k=profile.top_k,
                ),
            )
            # #region agent log
            candidates = getattr(response, "candidates", None) or []
            finish_reason = ""
            if candidates:
                finish_reason = str(getattr(candidates[0], "finish_reason", "") or "")
            prompt_feedback = getattr(response, "prompt_feedback", None)
            block_reason = ""
            if prompt_feedback:
                block_reason = str(getattr(prompt_feedback, "block_reason", "") or "")
            text_len = -1
            try:
                text_preview_val = response.text or ""
                text_len = len(text_preview_val)
            except Exception:
                text_preview_val = ""
            _debug_log(
                state.get("_trace_id", "") or state.get("_session_id", "unknown"),
                "H7",
                "langgraph_core.py:response_node",
                "raw_model_response_shape",
                {
                    "candidates_count": len(candidates),
                    "finish_reason": finish_reason,
                    "has_prompt_feedback": bool(prompt_feedback),
                    "block_reason": block_reason,
                    "response_text_len": text_len,
                    "response_text_preview": text_preview_val[:160],
                },
            )
            # #endregion
            
            # SAFETY CHECK: Check prompt_feedback BEFORE accessing response.text
            # When content is blocked by safety filters, response.text raises AttributeError
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                block_reason = getattr(response.prompt_feedback, 'block_reason', 'UNKNOWN')
                logger.warning(f"[RESPONSE] Content blocked by safety filter: {block_reason}")
                response_text = "Maaf, Pantronux. Respons diblokir oleh filter keamanan Gemini. Silakan ubah pertanyaan Anda."
            
            # Only access response.text if not blocked
            if response_text is None:
                try:
                    response_text = response.text if response.text else "Maaf, Pantronux. Kuro tidak dapat menghasilkan respons yang valid."
                except Exception as text_err:
                    if "WARNING" in str(text_err) or "Safety" in str(text_err) or "blocked" in str(text_err).lower():
                        logger.warning(f"[RESPONSE] response.text blocked: {text_err}")
                        response_text = "Maaf, Pantronux. Respons diblokir oleh filter keamanan Gemini."
                    else:
                        raise text_err
            # #region agent log
            _debug_log(
                state.get("_trace_id", "") or state.get("_session_id", "unknown"),
                "H5",
                "langgraph_core.py:response_node",
                "response_text_resolution",
                {
                    "response_text_is_none_after_resolution": response_text is None,
                    "response_text_preview": (response_text or "")[:200],
                },
            )
            # #endregion
            
            # Track token usage
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                prompt_tokens = response.usage_metadata.prompt_token_count or 0
                completion_tokens = response.usage_metadata.candidates_token_count or 0
                total_tokens = response.usage_metadata.total_token_count or (prompt_tokens + completion_tokens)
                # #region agent log
                _debug_log(
                    state.get("_trace_id", "") or state.get("_session_id", "unknown"),
                    "H8",
                    "langgraph_core.py:response_node",
                    "usage_metadata",
                    {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    },
                )
                # #endregion
                
                observability.track_token_usage(session_id, prompt_tokens, completion_tokens, total_tokens)
                
                if span:
                    span.set_attribute("response_node.prompt_tokens", prompt_tokens)
                    span.set_attribute("response_node.completion_tokens", completion_tokens)
                    span.set_attribute("response_node.total_tokens", total_tokens)
            
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error(f"[RESPONSE] LLM generation failed ({error_type}): {error_msg}")
            # Don't expose raw exception to user - use generic error message
            if response_text is None:
                    response_text = "Maaf, Pantronux. Terjadi kesalahan saat menghasilkan respons. Silakan coba lagi."

        # One-time V7 reset migration confirmation (Sebastian persona policy).
        global _v7_reset_announcement_sent
        with _v7_reset_announcement_lock:
            if not _v7_reset_announcement_sent:
                response_text = (
                    "Master, I have purged the unnecessary modules. "
                    "My memory is now focused solely on your core directives and facts.\n\n"
                    f"{response_text}"
                )
                _v7_reset_announcement_sent = True



        # Single consolidated persist path (short-term + enqueue memory_write + mem0_extract).
        # memory_extraction_node still runs as a dedupe/guardian, but mem0 fingerprint dedupe
        # in memory_coordinator prevents double-store.
        _persist_short_term_and_enqueue_writes(user_input, response_text, persona_mode)

        logger.info("[RESPONSE] Generated response (%s chars)", len(response_text))
        
        if span:
            span.set_attribute("response_node.response_length", len(response_text))
        
        return {
            "final_response": response_text,
        }


# ============================================
# NODE: TOOL EXECUTOR (The Hands)
# ============================================

# P2.3 — minimal tool-router instruction. Tool specs come from the Gemini
# function-calling declarations, so we only tell the router *how to route*.
# Persona, CoT and negative-constraint text are intentionally removed — the
# router doesn't generate the final answer and doesn't need them.
_TOOL_ROUTER_SYSTEM_INSTRUCTION = (
    "Kuro tool router. Pick at most ONE function_call for the user request. "
    "For read-only OpenClaw tasks use execution_mode='readonly', else 'mutating'. "
    "Use skill_name='harvest_gemini_share' for gemini.google.com/share links. "
    "For budgets, subscriptions, recurring expenses, or API spend use "
    "get_budget_tool, set_monthly_budget_tool, list_recurring_expenses_tool, "
    "add_recurring_expense_tool, or get_daily_api_cost_tool. "
    "For equities or live quotes use get_ticker_price_tool or get_market_news_tool; "
    "for prediction-market style odds use prediction_market_scan_tool (readonly OpenClaw). "
    "No tool matches? Reply with empty text."
)


def _collect_tool_calls(response: Any) -> List[Any]:
    """Extract function_calls from google-genai v3 response across SDK variants."""
    direct = getattr(response, "function_calls", None)
    if direct:
        return list(direct)
    calls: List[Any] = []
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            fc = getattr(part, "function_call", None)
            if fc is not None:
                calls.append(fc)
    return calls


def tool_node(state: KuroState) -> Dict[str, Any]:
    """
    Tool Node: delegates to a tool chosen by Gemini native function-calling.

    Tools available:
    - generate_excel_report
    - manage_files
    - generate_report_template
    - advanced_execution_tool (OpenClaw bridge)
    - set_monthly_budget_tool / get_budget_tool / add_recurring_expense_tool
    - list_recurring_expenses_tool / get_daily_api_cost_tool
    - get_ticker_price_tool / get_market_news_tool / prediction_market_scan_tool
    """
    from kuro_backend.tools.system_tools import (  # noqa: F401 (validates module import)
        generate_excel_report,
        generate_report_template,
        manage_files,
    )

    user_input = state.get("user_input", "")
    session_id = state.get("_session_id", "unknown")
    trace_attrs = observability.create_session_context(session_id=session_id)

    with observability.trace_node("tool_node", trace_attrs) as span:
        try:
            genai_client = _get_genai_client()

            router_tools = [
                generate_excel_report,
                manage_files,
                generate_report_template,
                kuro_tools.advanced_execution_tool,
                kuro_tools.set_monthly_budget_tool,
                kuro_tools.get_budget_tool,
                kuro_tools.add_recurring_expense_tool,
                kuro_tools.list_recurring_expenses_tool,
                kuro_tools.get_daily_api_cost_tool,
                kuro_tools.get_ticker_price_tool,
                kuro_tools.get_market_news_tool,
                kuro_tools.prediction_market_scan_tool,
            ]
            response = genai_client.models.generate_content(
                model=PRIMARY_MODEL,
                contents=user_input,
                config=genai_types.GenerateContentConfig(
                    system_instruction=_TOOL_ROUTER_SYSTEM_INSTRUCTION,
                    temperature=personas.ROUTER_SAMPLING_PROFILE.temperature,
                    top_p=personas.ROUTER_SAMPLING_PROFILE.top_p,
                    top_k=personas.ROUTER_SAMPLING_PROFILE.top_k,
                    max_output_tokens=personas.ROUTER_SAMPLING_PROFILE.max_output_tokens,
                    tools=router_tools,
                    tool_config=genai_types.ToolConfig(
                        function_calling_config=genai_types.FunctionCallingConfig(mode="AUTO")
                    ),
                ),
            )

            function_calls = _collect_tool_calls(response)
            # #region agent log
            finish_reason = ""
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                finish_reason = str(getattr(candidates[0], "finish_reason", "") or "")
            _debug_log(
                state.get("_trace_id", "") or state.get("_session_id", "unknown"),
                "H2",
                "langgraph_core.py:tool_node",
                "tool_router_response_shape",
                {
                    "function_calls_count": len(function_calls),
                    "finish_reason": finish_reason,
                    "response_text_preview": (getattr(response, "text", "") or "")[:160],
                },
            )
            # #endregion
            if not function_calls:
                reason = ""
                try:
                    reason = (response.text or "").strip()[:200]
                except Exception:
                    reason = ""
                logger.info("[TOOL_NODE] No function_call returned; falling through.")
                # #region agent log
                _debug_log(
                    state.get("_trace_id", "") or state.get("_session_id", "unknown"),
                    "H3",
                    "langgraph_core.py:tool_node",
                    "no_function_call_fallback",
                    {"reason_preview": reason[:160]},
                )
                # #endregion
                if span is not None:
                    span.set_attribute("tool_node.tool_used", "none")
                return {
                    "tool_execution_result": {"status": "no_tool", "message": reason},
                    "next_step": "response_node",
                }

            fc = function_calls[0]
            tool_name = getattr(fc, "name", None) or ""
            raw_args = getattr(fc, "args", None) or {}
            args: Dict[str, Any] = dict(raw_args) if isinstance(raw_args, dict) else {}
            # #region agent log
            _debug_log(
                state.get("_trace_id", "") or state.get("_session_id", "unknown"),
                "H4",
                "langgraph_core.py:tool_node",
                "selected_tool_call",
                {
                    "tool_name": tool_name,
                    "args_keys": sorted(list(args.keys()))[:20],
                    "args_type": str(type(raw_args)),
                },
            )
            # #endregion

            if not tool_name:
                if span is not None:
                    span.set_attribute("tool_node.tool_used", "none")
                return {
                    "tool_execution_result": {"status": "no_tool", "message": ""},
                    "next_step": "response_node",
                }

            # Check for HITL interrupt (file write/delete operations)
            action = args.get("action", "")

            high_risk_text = f"{user_input} {json.dumps(args, ensure_ascii=False)}"
            openclaw_risky = tool_name == "advanced_execution_tool" and _contains_destructive_keyword(high_risk_text)
            if tool_name == "advanced_execution_tool":
                if args.get("read_only") is True and "execution_mode" not in args:
                    args["execution_mode"] = "readonly"
                execution_mode = str(args.get("execution_mode", "mutating")).strip().lower()
                args["execution_mode"] = "readonly" if execution_mode == "readonly" else "mutating"
            else:
                execution_mode = "mutating"
            openclaw_read_only_flag = execution_mode == "readonly" if tool_name == "advanced_execution_tool" else False
            openclaw_read_only = openclaw_read_only_flag
            openclaw_requires_approval = (
                tool_name == "advanced_execution_tool"
                and not openclaw_read_only
            )

            requires_approval = (
                action in ["write", "delete"]
                or tool_name in ["generate_excel_report", "generate_report_template"]
                or openclaw_requires_approval
                or openclaw_risky
            )
            
            if requires_approval:
                logger.info(f"[TOOL_NODE] HITL interrupt required for {tool_name}:{action}")
                approval_scope = state.get("_approval_scope", "default")
                reason = (
                    "Perintah berisiko/destruktif terdeteksi. "
                    "Kirim approval nonce untuk melanjutkan."
                    if openclaw_risky
                    else (
                        "Aksi advanced_execution_tool non-read-only membutuhkan persetujuan Master. "
                        "Kirim approval nonce untuk lanjut."
                        if openclaw_requires_approval
                        else "Aksi tulis/generate membutuhkan persetujuan Master."
                    )
                )
                # Persist pending action; execution is strictly blocked until approval token is received.
                nonce = _set_pending_approval(
                    approval_scope,
                    tool_name,
                    args,
                    reason,
                    trace_id=state.get("_trace_id", ""),
                )
                if span:
                    span.set_attribute("tool_node.requires_approval", True)
                    span.set_attribute("tool_node.tool_name", tool_name)
                return {
                    "tool_execution_result": {
                        "status": "pending_approval",
                        "tool": tool_name,
                        "args": args,
                        "message": f"{reason} Balas: approve {nonce}",
                    },
                    "requires_approval": True,
                    "next_step": "response_node"  # Go to response to ask for approval
                }
            
            # Execute tool
            tool_result = _execute_tool(tool_name, args)
            
            if span:
                span.set_attribute("tool_node.tool_name", tool_name)
                span.set_attribute("tool_node.tool_result_status", tool_result.get("status", "unknown"))
            
            logger.info(f"[TOOL_NODE] Executed {tool_name}: {tool_result.get('status', 'unknown')}")
            
            return {
                "tool_execution_result": tool_result,
                "next_step": "response_node"  # After tool, go to response to inform user
            }
            
        except Exception as e:
            logger.error(f"[TOOL_NODE] Tool execution failed: {e}")
            return {
                "tool_execution_result": {"status": "error", "message": str(e)},
                "next_step": "response_node"
            }


def _execute_tool(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a specific tool with given arguments."""
    from kuro_backend.tools.system_tools import (
        generate_excel_report,
        manage_files,
        generate_report_template,
    )
    
    tools_map = {
        "generate_excel_report": generate_excel_report,
        "manage_files": manage_files,
        "generate_report_template": generate_report_template,
        "advanced_execution_tool": kuro_tools.advanced_execution_tool,
        "set_monthly_budget_tool": kuro_tools.set_monthly_budget_tool,
        "get_budget_tool": kuro_tools.get_budget_tool,
        "add_recurring_expense_tool": kuro_tools.add_recurring_expense_tool,
        "list_recurring_expenses_tool": kuro_tools.list_recurring_expenses_tool,
        "get_daily_api_cost_tool": kuro_tools.get_daily_api_cost_tool,
        "get_ticker_price_tool": kuro_tools.get_ticker_price_tool,
        "get_market_news_tool": kuro_tools.get_market_news_tool,
        "prediction_market_scan_tool": kuro_tools.prediction_market_scan_tool,
    }
    
    tool_func = tools_map.get(tool_name)
    if not tool_func:
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}
    
    try:
        if hasattr(tool_func, "invoke"):
            result = tool_func.invoke(args)
        else:
            result = tool_func(**args)
        return {"status": "success", "tool": tool_name, "result": result}
    except Exception as e:
        return {"status": "error", "tool": tool_name, "message": str(e)}


# ============================================
# ROUTING LOGIC (Conditional Edges)
# ============================================

def route_after_supervisor(state: KuroState) -> str:
    """Determine next node based on supervisor decision."""
    next_step = state.get("next_step", "response_node")
    # Map END constant to string for routing
    if next_step == END:
        return "__end__"
    return next_step


# ============================================
# GRAPH CONSTRUCTION
# ============================================

def build_kuro_graph() -> StateGraph:
    """
    Build the Kuro LangGraph state machine.
    
    Graph Structure:
    START -> supervisor_node -> memory_retrieval -> [tool_node | response_node] -> response_node -> memory_extraction -> END
    """
    
    # Initialize checkpointer for persistence
    checkpointer = MemorySaver()
    
    # Create state graph
    graph_builder = StateGraph(KuroState)
    
    # Add nodes
    graph_builder.add_node("reflection_node", reflection_node)
    graph_builder.add_node("supervisor_node", supervisor_node)
    graph_builder.add_node("memory_retrieval_node", memory_retrieval_node)
    graph_builder.add_node("tool_node", tool_node)
    graph_builder.add_node("response_node", response_node)
    graph_builder.add_node("memory_extraction_node", memory_extraction_node)
    
    # Set entry point using START constant (LangGraph v0.2+ compatible)
    graph_builder.add_edge(START, "reflection_node")
    graph_builder.add_edge("reflection_node", "supervisor_node")
    
    # After supervisor, run memory retrieval in parallel
    graph_builder.add_edge("supervisor_node", "memory_retrieval_node")
    
    # Add conditional edges from memory retrieval
    graph_builder.add_conditional_edges(
        "memory_retrieval_node",
        route_after_supervisor,
        {
            "tool_node": "tool_node",
            "response_node": "response_node",
            "__end__": END,
        }
    )
    
    # Add edges from worker nodes to response
    graph_builder.add_edge("tool_node", "response_node")
    
    # V5.5: Direct edge from response_node to memory_extraction_node (no re-ask loop)
    graph_builder.add_edge("response_node", "memory_extraction_node")
    
    # After memory extraction, go to END
    graph_builder.add_edge("memory_extraction_node", END)
    
    # Compile with checkpointer
    graph = graph_builder.compile(checkpointer=checkpointer)
    
    logger.info("[LANGGRAPH] Kuro graph compiled successfully with tool_node")
    return graph


# Global graph instance
kuro_graph = build_kuro_graph()


def _iter_sse_text_chunks(text: str, soft_limit: int = 56) -> Iterator[str]:
    """
    Split assistant text for SSE after guardrails. Prefer word boundaries so the web UI
    does not run marked.parse on half-open markdown tokens (empty / broken bubbles).
    """
    if not text:
        return
    if not text.strip():
        yield text
        return
    buf: List[str] = []
    size = 0
    for m in re.finditer(r"\S+\s*", text):
        w = m.group(0)
        if len(w) > soft_limit:
            if buf:
                yield "".join(buf)
                buf = []
                size = 0
            for i in range(0, len(w), soft_limit):
                yield w[i : i + soft_limit]
            continue
        if size + len(w) > soft_limit and buf:
            yield "".join(buf)
            buf = []
            size = 0
        buf.append(w)
        size += len(w)
    if buf:
        yield "".join(buf)


def _sync_stream_collect_final_response(initial_state: Dict[str, Any], config: Dict[str, Any]) -> str:
    """Run sync LangGraph stream in a worker thread (keeps asyncio event loop free for SSE)."""
    raw: Optional[str] = None
    for event in kuro_graph.stream(initial_state, config=config, stream_mode="updates"):
        for node_name, node_output in event.items():
            if node_name != "response_node":
                continue
            text = (node_output or {}).get("final_response")
            if text is None:
                continue
            s = str(text)
            if s.strip():
                raw = s
            elif raw is None:
                raw = s
    return raw if raw is not None else ""


def _split_head_for_early_flush(text: str) -> tuple[str, str]:
    """First sentence or first line first, so SSE can flush before chunking the rest."""
    if not text:
        return "", ""
    head_cap = min(len(text), 1200)
    head_candidate = text[:head_cap]
    m = re.search(r"(?<=[.!?。！？])\s+", head_candidate)
    if m:
        end = m.end()
        return text[:end], text[end:]
    nl = text.find("\n")
    if nl != -1:
        return text[: nl + 1], text[nl + 1 :]
    return "", text


# ============================================
# ASYNC STREAMING ENTRY POINT (Project Quicksilver V5.5)
# ============================================

async def process_chat_with_graph_stream(
    message: str,
    image_paths: Optional[List[str]] = None,
    persona_override: Optional[str] = None,
    stream_metrics: Optional[Dict[str, Any]] = None,
    approval_scope: str = "default",
    trace_id: str = "",
) -> AsyncGenerator[str, None]:
    """
    V5.5 STREAMING: Graph runs in asyncio.to_thread (sync stream) so the event loop can serve SSE.
    Sniper input/output checks use async wrappers (Gemini/NeMo in thread pool).
    After postprocess, first sentence/line is yielded once with flush, then word-chunked tail.
    
    Args:
        message: User message
        image_paths: Optional list of image paths for vision
    
    Yields:
        Response text chunks as they are generated (ONLY from response_node)
    """
    session_id = str(uuid.uuid4())
    full_response = []
    response_text = ""

    try:
        stage_started = time.perf_counter()
        approval_response = _maybe_handle_pending_approval(message, approval_scope)
        if approval_response is not None:
            yield approval_response
            return



        persona_mode = memory_manager.normalize_persona(
            persona_override or memory_manager.get_active_persona()
        )

        # P3.1 — Semantic cache lookup BEFORE committing to any LLM path.
        # Disabled by default; opt-in via KURO_SEMANTIC_CACHE_ENABLED.
        if not image_paths:
            from kuro_backend import semantic_cache
            cached_response = semantic_cache.lookup(message, persona_mode)
            if cached_response is not None:
                if stream_metrics is not None:
                    stream_metrics["stream_mode"] = "semantic_cache"
                yield cached_response
                try:
                    _persist_short_term_and_enqueue_writes(message, cached_response, persona_mode)
                except Exception as exc:
                    logger.warning("[SEMANTIC_CACHE] persist failed: %s", exc)
                return

        can_use_true_stream = (
            _TRUE_TOKEN_STREAMING_ENABLED
            and not image_paths
        )
        if stream_metrics is not None:
            stream_metrics["stream_mode"] = "true_token_fastpath" if can_use_true_stream else "graph_collect_chunked"

        if can_use_true_stream:
            fastpath_started = time.perf_counter()
            memory_coordinator.apply_path_tokens_to_runtime(message, persona_mode)
            memory_started = time.perf_counter()
            ctx = await memory_coordinator.build_context_for_llm_async(
                message,
                persona_mode,
                mem0_retrieved_memories=None,
            )
            if stream_metrics is not None:
                stream_metrics["memory_query_ms"] = round((time.perf_counter() - memory_started) * 1000, 2)
            memory_injection = ctx["memory_injection"]
            mem0_block = ctx.get("mem0_context_block") or ""
            ref_block = ctx.get("referent_grounding_block") or ""
            fin_block = ctx.get("finance_block") or ""
            mkt_block = ctx.get("market_block") or ""
            if mem0_block:
                memory_injection = f"\n\n[USER_CONTEXT - PERPETUAL MEMORY]\n{mem0_block}{memory_injection}"
            if fin_block:
                memory_injection = f"\n\n{fin_block}{memory_injection}"
            if mkt_block:
                memory_injection = f"\n\n{mkt_block}{memory_injection}"
            prefix = message
            if ref_block:
                prefix = f"{message}\n\n{ref_block}"
            full_message = f"{prefix}{memory_injection}"
            system_prompt = get_system_instruction(persona_override=persona_mode)

            emitted = 0
            response_acc: List[str] = []
            stream_llm_started = time.perf_counter()
            async for live_chunk in _stream_direct_llm_chunks(system_prompt, full_message, persona_mode=persona_mode):
                response_acc.append(live_chunk)
                emitted += 1
                yield live_chunk
            if stream_metrics is not None:
                stream_metrics["llm_stream_ms"] = round((time.perf_counter() - stream_llm_started) * 1000, 2)
                stream_metrics["sse_chunk_count"] = float(emitted)

            response_text = "".join(response_acc).strip()
            if not response_text:
                response_text = "Maaf, Pantronux. Respons model kosong setelah streaming."
                yield response_text
                emitted += 1
            _persist_short_term_and_enqueue_writes(message, response_text, persona_mode)
            # P3.1 — cache the fastpath response for near-duplicate queries.
            try:
                from kuro_backend import semantic_cache
                semantic_cache.store(
                    message,
                    persona_mode,
                    response_text,
                    tags=semantic_cache.classify_tags(message),
                )
            except Exception as exc:
                logger.debug("[SEMANTIC_CACHE] store skipped: %s", exc)
            if stream_metrics is not None:
                stream_metrics["response_chars"] = float(len(response_text))
                stream_metrics["stream_total_ms"] = round((time.perf_counter() - fastpath_started) * 1000, 2)
            return
        
        initial_state = {
            "messages": [{"role": "user", "content": message}],
            "next_step": "",
            "user_input": message,
            "final_response": "",
            "persona_mode": persona_mode,
            "image_paths": image_paths,
            "mem0_retrieved_memories": [],
            "tool_execution_result": {},
            "requires_approval": False,
            "_session_id": session_id,
            "_approval_scope": approval_scope,
            "_trace_id": trace_id,
        }
        
        thread_id = f"kuro_stream_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{session_id[:8]}"
        config = {"configurable": {"thread_id": thread_id}}
        
        logger.debug("[LANGGRAPH_STREAM] graph invoke (thread offload) preview=%.50s", message)

        graph_started = time.perf_counter()
        raw_model_response = await asyncio.to_thread(
            _sync_stream_collect_final_response, initial_state, config
        )
        if stream_metrics is not None:
            stream_metrics["graph_collect_ms"] = round((time.perf_counter() - graph_started) * 1000, 2)
        if raw_model_response is None:
            raw_model_response = ""
        logger.debug(
            "[LANGGRAPH_STREAM] model bytes=%s (sniper postprocess next)",
            len(raw_model_response),
        )

        response_text = raw_model_response
        if stream_metrics is not None:
            stream_metrics["guardrail_output_ms"] = 0.0
        if response_text is None:
            response_text = ""
        if not str(response_text).strip():
            response_text = (
                "Maaf, Pantronux. Respons model kosong setelah pemeriksaan. Silakan ulangi pertanyaan."
            )
            logger.warning("[LANGGRAPH_STREAM] empty model text after postprocess; sent fallback bubble")
        if response_text:
            head, tail = _split_head_for_early_flush(response_text)
            if head:
                full_response.append(head)
                yield head
                await asyncio.sleep(0)
                chunk_iter = _iter_sse_text_chunks(tail)
            else:
                chunk_iter = _iter_sse_text_chunks(response_text)
            for i, chunk in enumerate(chunk_iter):
                full_response.append(chunk)
                yield chunk
                if i == 0 and not head:
                    await asyncio.sleep(0)
                else:
                    await asyncio.sleep(0.012)
            logger.debug("[LANGGRAPH_STREAM] yielded total_chars=%s", len(response_text))
            if stream_metrics is not None:
                stream_metrics["response_chars"] = float(len(response_text))
                stream_metrics["sse_chunk_count"] = float(len(full_response))

        # Memory: response_node already persists short/long-term; avoid duplicate writes here.
        # chat_history: main.py /api/chat/stream adds assistant message after the generator finishes.

        logger.debug("[LANGGRAPH_STREAM] streaming complete chars=%s", len(response_text))
        if stream_metrics is not None:
            stream_metrics["stream_total_ms"] = round((time.perf_counter() - stage_started) * 1000, 2)
        
    except Exception as e:
        logger.exception(f"[LANGGRAPH_STREAM] Streaming failed: {e}")
        error_msg = "Maaf, Pantronux. Terjadi kesalahan saat memproses permintaan Anda."
        yield error_msg
        full_response = [error_msg]


# ============================================
# ASYNC PDF PROCESSING WITH SSE THINKING SIGNALS (AFC Optimization)
# ============================================

async def process_pdf_with_thinking(
    file_path: str,
    max_pages: int = 50,
    max_chars: int = 50000
) -> AsyncGenerator[str, None]:
    """
    Process PDF with SSE "Kuro is thinking..." signals to prevent browser timeout.
    
    This function:
    1. Sends periodic "thinking" signals to keep SSE connection alive
    2. Processes PDF chunks with timeout protection
    3. Yields progress updates and final content
    
    Args:
        file_path: Path to the PDF file
        max_pages: Maximum pages to process
        max_chars: Maximum characters to return
    
    Yields:
        Progress signals and extracted content
    """
    from kuro_backend.tools.base_tools import (
        read_pdf_content,
        PDF_PROCESSING_TIMEOUT_SECONDS,
        PDF_CHUNK_PROCESSING_TIMEOUT
    )
    
    # Verify file exists
    if not os.path.exists(file_path):
        yield f"\n\n⚠️ File not found: {file_path}\n\n"
        return
    
    # Send initial thinking signal
    yield "\n\n📄 Kuro is analyzing PDF document...\n\n"
    
    start_time = time.time()
    
    # Define progress callback for SSE signals
    thinking_signals_sent = []
    
    def progress_callback(current_page: int, total_pages: int):
        """Send 'Kuro is thinking...' signal for each chunk processed."""
        elapsed = time.time() - start_time
        
        # Check timeout
        if elapsed > PDF_PROCESSING_TIMEOUT_SECONDS:
            raise TimeoutError(f"PDF processing exceeded timeout ({PDF_PROCESSING_TIMEOUT_SECONDS}s)")
        
        # Calculate progress percentage
        progress_pct = (current_page / total_pages) * 100
        
        # Send thinking signal every 5 pages or at key milestones
        if current_page % 5 == 0 or current_page == total_pages:
            signal = f"\n📖 Kuro is thinking... Processing page {current_page}/{total_pages} ({progress_pct:.0f}%)\n"
            thinking_signals_sent.append(signal)
    
    try:
        # Process PDF with progress callback
        pdf_result = read_pdf_content(
            file_path=file_path,
            max_pages=max_pages,
            max_chars=max_chars,
            progress_callback=progress_callback
        )
        
        # Check for errors
        if pdf_result.get("error"):
            yield f"\n\n⚠️ PDF Processing Error: {pdf_result['error']}\n\n"
            return
        
        # Send completion signal
        elapsed = time.time() - start_time
        yield f"\n\n✅ PDF analysis complete in {elapsed:.1f}s\n"
        yield f"📊 Pages: {pdf_result.get('page_count', 0)} | Tables found: {pdf_result.get('tables_found', 0)}\n\n"
        
        # Yield extracted content
        content = pdf_result.get("content", "")
        if content:
            yield content
        else:
            yield "\n\n⚠️ No text content could be extracted from this PDF.\n\n"
        
    except TimeoutError as te:
        logger.warning(f"[PDF_PROCESSING] Timeout after {time.time() - start_time:.1f}s: {te}")
        yield f"\n\n⏱️ PDF processing timed out after {PDF_PROCESSING_TIMEOUT_SECONDS} seconds. The document may be too large or complex.\n\n"
    except Exception as e:
        logger.exception(f"[PDF_PROCESSING] Failed: {e}")
        yield f"\n\n⚠️ PDF processing failed: {str(e)}\n\n"


# ============================================
# MAIN ENTRY POINT (Backward Compatible)
# ============================================

def process_chat_with_graph(
    message: str,
    image_paths: Optional[List[str]] = None,
    persona_override: Optional[str] = None,
    approval_scope: str = "sync_default",
    trace_id: str = "",
) -> str:
    """
    Process chat message using LangGraph state machine.
    Backward compatible with existing process_chat() signature.
    
    Args:
        message: User message
        image_paths: Optional list of image paths for vision
    
    Returns:
        Generated response string
    """
    # Generate unique session ID for observability
    session_id = str(uuid.uuid4())
    
    try:
        approval_response = _maybe_handle_pending_approval(message, approval_scope)
        if approval_response is not None:
            return approval_response



        # Get current persona
        persona_mode = memory_manager.normalize_persona(
            persona_override or memory_manager.get_active_persona()
        )

        # P3.1 — semantic cache lookup on the sync path as well.
        if not image_paths:
            from kuro_backend import semantic_cache
            cached_response = semantic_cache.lookup(message, persona_mode)
            if cached_response is not None:
                try:
                    _persist_short_term_and_enqueue_writes(message, cached_response, persona_mode)
                except Exception as exc:
                    logger.warning("[SEMANTIC_CACHE] persist failed: %s", exc)
                return cached_response

        # Initialize state with session ID for observability
        initial_state = {
            "messages": [{"role": "user", "content": message}],
            "next_step": "",
            "user_input": message,
            "final_response": "",
            "persona_mode": persona_mode,
            "image_paths": image_paths,
            "mem0_retrieved_memories": [],
            "tool_execution_result": {},
            "requires_approval": False,
            "_session_id": session_id,  # Internal field for observability
            "_approval_scope": approval_scope,
            "_trace_id": trace_id,
        }

        # Create unique thread ID for persistence
        thread_id = f"kuro_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        config = {"configurable": {"thread_id": thread_id}}

        # Invoke graph
        logger.info(f"[LANGGRAPH] Invoking graph for message: {message[:50]}... (session: {session_id})")
        final_state = kuro_graph.invoke(initial_state, config=config)
        
        # Extract response
        response = final_state.get("final_response", "")
        
        if not response:
            logger.warning("[LANGGRAPH] Empty response from graph")
            return "Maaf, Pantronux. Respons tidak tersedia untuk saat ini. Mohon ulangi instruksi."
        # P3.1 — store response for future semantic reuse.
        try:
            from kuro_backend import semantic_cache
            semantic_cache.store(
                message,
                persona_mode,
                response,
                tags=semantic_cache.classify_tags(message),
            )
        except Exception as exc:
            logger.debug("[SEMANTIC_CACHE] store (sync) skipped: %s", exc)
        return response
        
    except Exception as e:
        logger.exception(f"[LANGGRAPH] Graph invocation failed: {e}")
        return "Maaf, Pantronux. Kuro mengalami kendala sistem. Silakan coba lagi."


# ============================================
# GRAPH VISUALIZATION (Debug)
# ============================================

def save_graph_visualization(path: str = "kuro_graph.png") -> None:
    """No-op placeholder kept for API compatibility.

    Real rendering requires graphviz/IPython which are optional in prod.
    """
    logger.debug("[LANGGRAPH] save_graph_visualization no-op (target=%s)", path)
