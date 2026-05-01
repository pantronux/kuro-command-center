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
Side Effects: LLM API calls (Gemini), SQLite reads via memory/finance/intelligence, Mem0 reads, token-usage metrics, semantic-cache writes, threading primitives for fastpath.
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
        username = task.get("username", "Pantronux")
        persona_scope = task.get("persona_scope") or memory_manager.get_active_persona(username)
        memory_coordinator.execute_memory_write_task(user_input, final_response, persona_scope)
    elif kind == "mem0_extract":
        user_input = task.get("user_input", "")
        final_response = task.get("final_response", "")
        username = task.get("username", "Pantronux")
        memory_coordinator.execute_mem0_extract_task(user_input, final_response, username)
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


def _persist_short_term_and_enqueue_writes(user_input: str, response_text: str, persona_mode: str, username: str = "Pantronux") -> None:
    memory_manager.add_short_term("user", user_input, persona_scope=persona_mode, username=username)
    memory_manager.add_short_term("assistant", response_text, persona_scope=persona_mode, username=username)


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

            # Use cached content if configured
            config_kwargs = {
                "system_instruction": system_prompt,
                "temperature": profile.temperature,
                "top_p": profile.top_p,
                "top_k": profile.top_k,
                "tools": [{"google_search": {}}],
            }

            if settings.GEMINI_CACHED_CONTENT:
                config_kwargs["cached_content"] = settings.GEMINI_CACHED_CONTENT

            stream = client.models.generate_content_stream(
                model=PRIMARY_MODEL,
                contents=full_message,
                config=genai_types.GenerateContentConfig(**config_kwargs),
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
    V7.2: Natural Agency (Tomasello 2025) tier fields added.

    Core Fields:
    - messages: Conversation history (list of dicts with role/content)
    - next_step: Next node to route to (supervisor decision)
    - user_input: Original user message
    - final_response: Generated response to return
    - persona_mode: Current active persona
    - mem0_retrieved_memories: Memories retrieved from Mem0 for context
    - tool_execution_result: Result from tool execution (ToolNode output)
    - requires_approval: Flag for HITL interrupt (file operations need approval)

    T1 Executive / Intentional Agent:
    - inhibited: True if prepotent response was withheld
    - inhibition_reason: Why it was withheld
    - simulated_outcomes: List of {"label", "strategy", "novelty_score"/"adversarial_score"}
    - selected_outcome: The chosen simulation dict
    - cognitive_effort: "low" | "medium" | "high" — controls CoT depth

    T2 Metacognitive / Rational Agent:
    - alignment_score: 0.0–1.0 alignment with BRD commitments
    - metacognitive_flag: True triggers reflective_response_node instead of normal response

    T3 Shared Agency / Social Agent:
    - joint_goal_block: Formatted active commitments injected into system prompt
    - _intent_category: Attention filter tag (dissertation/research/off_track/administrative)
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
    # --- Natural Agency fields (V7.2) ---
    _intent_category: str
    inhibited: bool
    inhibition_reason: str
    simulated_outcomes: List[Dict]
    selected_outcome: Optional[Dict]
    cognitive_effort: str
    alignment_score: float
    metacognitive_flag: bool
    joint_goal_block: str
    # --- Auto-RAG fields (V7.2.1 Self-Correction Loop) ---
    retrieval_grade: str          # "relevant" | "ambiguous" | "irrelevant"
    retrieval_retry_count: int    # bounded 0–2; failover to Serper at max
    rewritten_query: str          # LLM-transformed query after grading fail
    master_name: str              # User-specific name (e.g. Pantronux, Master Faikhira)
    username: str                 # System username for memory isolation


# ============================================
# PERSONA SYSTEM (shared with core.py via kuro_backend.personas)
# ============================================


def get_system_instruction(persona_override: Optional[str] = None, master_name: str = "Pantronux") -> str:
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
        master_name=master_name,
    )

# ============================================
# NODE: REFLECTION (Task Continuity)
# ============================================

def reflection_node(state: KuroState) -> Dict[str, Any]:
    """
    Pre-Processing Reflection Node (V7.2.1 Task Continuity) with LLM-Based Intent Router.
    Determines if the Master's intent is "Editing", "Adding", or "Revising".
    """
    user_input = state.get("user_input", "").lower()
    intent = "new"

    # Fast LLM-Based Intent Router (using Gemini Flash via _get_genai_client)
    try:
        from kuro_backend.config import CLASSIFIER_MODEL
        genai_client = _get_genai_client()

        prompt = f"""
Determine the user's intent based on this message: "{user_input}"

If the user is asking to modify, revise, add to, or correct the PREVIOUS response (e.g., "jangan pakai itu", "tambahin bagian ini", "ubah warnanya", "yang tadi salah"), output ONLY the word "edit".
If the user is asking a brand new question or starting a new topic, output ONLY the word "new".

Intent:"""

        response = genai_client.models.generate_content(
            model=CLASSIFIER_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=10,
            ),
        )

        if response.text:
            llm_intent = response.text.strip().lower()
            if "edit" in llm_intent:
                intent = "edit"
                logger.info(f"[REFLECTION] LLM Router detected 'edit' intent for: {user_input[:50]}...")
            elif "new" in llm_intent:
                intent = "new"
                logger.info(f"[REFLECTION] LLM Router detected 'new' intent for: {user_input[:50]}...")
            else:
                logger.warning(f"[REFLECTION] Unexpected LLM intent response: {llm_intent}. Falling back to heuristics.")
                raise ValueError("Unexpected LLM output")

    except Exception as e:
        logger.warning(f"[REFLECTION] LLM Intent Router failed: {e}. Using heuristic fallback.")
        # Fallback to simple heuristic
        edit_keywords = [
            "edit", "add", "revise", "revisi", "tambah", "ubah", "perbaiki",
            "lanjut", "sekali lagi", "update", "koreksi", "ganti",
            "tambahin", "lanjutin", "terusin", "modify", "adjust"
        ]

        if any(kw in user_input for kw in edit_keywords):
            referential_keywords = ["yang tadi", "sebelumnya", "hasil", "itu", "ini", "jawaban", "output", "the previous", "that"]
            if any(ref in user_input for ref in referential_keywords) or len(user_input.split()) <= 15:
                intent = "edit"
                logger.info(f"[REFLECTION] Heuristic fallback detected Edit/Update based on input: {user_input[:50]}...")

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
    # Auto-RAG: use rewritten query on retry passes
    effective_query = state.get("rewritten_query") or user_input

    with observability.trace_node("memory_retrieval_node") as span:
        try:
            # P1.2 — consume supervisor's prefetch if present; otherwise fall
            # back to a live retrieval using effective_query (may be rewritten).
            raw_memories = memory_coordinator.take_prefetched_mem0(session_id)
            username = state.get("username", "Pantronux")
            if raw_memories is None:
                raw_memories = memory_coordinator.safe_mem0_retrieve(effective_query, limit=5, username=username)

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
    """
    V7.2.1 Memory Extraction Node: Consolidates Mem0 usage as a Declarative Fact Store.
    Only triggers memory extraction when a task is successfully completed and NOT during an edit cycle.
    """
    user_input = state.get("user_input", "")
    final_response = state.get("final_response", "")
    tool_result = state.get("tool_execution_result", {})
    intent = state.get("_intent", "new")

    # 1. Guard Clause: Jangan jalankan ekstraksi jika respon asisten kosong
    # Ini mencegah penyimpanan memori yang tidak lengkap atau error API
    if not final_response or len(final_response.strip()) == 0:
        logger.warning("[MEM0_EXTRACTION] Skipped: No final_response found in state.")
        return {}

    # V7.2.1 Guard Clause: Skip extraction during edit/revision loops
    if intent == "edit":
        logger.info("[MEM0_EXTRACTION] Skipped: Currently in 'edit' intent cycle.")
        return {}

    task_success = False
    if tool_result.get("status") == "success":
        task_success = True
    
    success_keywords = ["thanks", "terima kasih", "selesai", "fixed", "done", "berhasil", "sip", "ok", "confirmed"]
    if any(kw in user_input.lower() for kw in success_keywords):
        task_success = True

    if not task_success:
        # LLM-based semantic check for task success / conclusion
        try:
            from kuro_backend.config import CLASSIFIER_MODEL
            genai_client = _get_genai_client()
            prompt = f"""
Determine if the user's message indicates that a task has been completed, a conclusion has been reached, or if the user is expressing gratitude/agreement that signals the end of an interaction.

User's message: "{user_input}"

If yes, output ONLY the word "success".
If no, output ONLY the word "continue".

Status:"""
            response = genai_client.models.generate_content(
                model=CLASSIFIER_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=10,
                ),
            )
            if response.text and "success" in response.text.strip().lower():
                task_success = True
                logger.info(f"[MEM0_EXTRACTION] LLM Router detected task completion for: {user_input[:50]}...")
        except Exception as e:
            logger.warning(f"[MEM0_EXTRACTION] Semantic task check failed: {e}")

    if task_success:
        with observability.trace_node("memory_extraction_node"):
            username = state.get("username", "Pantronux")
            _enqueue_post_response_task(
                {
                    "kind": "mem0_extract",
                    "user_input": user_input,
                    "final_response": final_response,
                    "username": username,
                }
            )
            logger.info("[MEM0_EXTRACTION] Triggering Mem0 extraction (Task Completed successfully).")
    else:
        logger.info("[MEM0_EXTRACTION] Skipped: Task not explicitly completed.")
    return {}


# ============================================
# AUTO-RAG: SELF-CORRECTION LOOP (V7.2.1)
# References: Self-RAG (Asai et al. 2023), CRAG (Yan et al. 2024),
#             Adaptive-RAG (Jeong et al. 2024)
# ============================================

_RAG_MAX_RETRIES: int = 2  # hard ceiling — prevents token-burn loops


def retrieval_grader_node(state: KuroState) -> Dict[str, Any]:
    """
    Auto-RAG Step 1 — Retrieval Quality Grader.

    Evaluates whether Mem0-retrieved memories are relevant to the current
    user_input using CLASSIFIER_MODEL. Fast path: if Mem0 returned nothing,
    grade immediately as 'irrelevant' without an LLM call.

    Grades:
      "relevant"   → context is useful; proceed to attention_filter_node.
      "ambiguous"  → context is partially useful; attempt query rewrite.
      "irrelevant" → context is useless; trigger query_transform_node.

    --- Header Doc ---
    Purpose: CRAG-style retrieval quality gating (Yan et al. 2024).
    Caller: memory_retrieval_node (via graph edge).
    Dependencies: CLASSIFIER_MODEL, genai_types.
    Main Functions: retrieval_grader_node(state) -> Dict
    Side Effects: None (read-only evaluation).
    """
    user_input = state.get("user_input", "")
    memories: List[Dict] = state.get("mem0_retrieved_memories") or []
    retry_count: int = state.get("retrieval_retry_count", 0)

    # ── Fast path: nothing retrieved ─────────────────────────────────────────
    if not memories:
        logger.info("[RAG_GRADER] No memories retrieved — grade=irrelevant")
        return {"retrieval_grade": "irrelevant"}

    # Summarise retrieved context for the grader prompt (cap at 1200 chars)
    context_preview = "\n".join(
        f"- {m.get('memory', m.get('content', str(m)))}" for m in memories[:6]
    )[:1200]

    try:
        from kuro_backend.config import CLASSIFIER_MODEL
        client = _get_genai_client()

        prompt = (
            "You are a strict retrieval quality judge.\n\n"
            f"User Query:\n{user_input}\n\n"
            f"Retrieved Context:\n{context_preview}\n\n"
            "Grade whether the retrieved context is useful for answering the query.\n"
            "Reply with ONLY one of these words: relevant | ambiguous | irrelevant\n"
            "- relevant:   context directly addresses the query.\n"
            "- ambiguous:  context is partially related or vague.\n"
            "- irrelevant: context does not address the query at all.\n\n"
            "Grade:"
        )
        resp = client.models.generate_content(
            model=CLASSIFIER_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=5,
            ),
        )
        raw = (resp.text or "").strip().lower().split()[0] if resp.text else ""
        grade = raw if raw in ("relevant", "ambiguous", "irrelevant") else "ambiguous"
    except Exception as exc:
        logger.warning("[RAG_GRADER] Grading failed (%s) — defaulting to relevant", exc)
        grade = "relevant"

    logger.info(
        "[RAG_GRADER] retry=%d grade=%s memories=%d",
        retry_count, grade, len(memories),
    )
    return {"retrieval_grade": grade}


def query_transform_node(state: KuroState) -> Dict[str, Any]:
    """
    Auto-RAG Step 2 — Query Rewriter & Serper Failover.

    Called when retrieval_grade is NOT 'relevant'.

    Behaviour:
      - If retry_count < _RAG_MAX_RETRIES: rewrite user_input into a more
        precise search query and bump retrieval_retry_count. The graph loops
        back to memory_retrieval_node with the rewritten_query in state.
      - If retry_count == _RAG_MAX_RETRIES: invoke Serper web search as a
        last-resort retrieval, inject results into mem0_retrieved_memories,
        and force retrieval_grade="relevant" to unblock the pipeline.

    Token-burn protection: bounded by _RAG_MAX_RETRIES=2 (max 2 extra
    CLASSIFIER_MODEL calls + 1 Serper HTTP call per turn).

    --- Header Doc ---
    Purpose: Self-RAG query optimiser and web-search failover.
    Caller: retrieval_grader_node (via conditional edge).
    Dependencies: CLASSIFIER_MODEL, serper_tool.serper_search.
    Main Functions: query_transform_node(state) -> Dict
    Side Effects: May call Serper API (network I/O).
    """
    user_input = state.get("user_input", "")
    rewritten = state.get("rewritten_query") or user_input
    retry_count: int = state.get("retrieval_retry_count", 0)
    grade = state.get("retrieval_grade", "irrelevant")

    # ── Serper failover at max retries ────────────────────────────────────────
    if retry_count >= _RAG_MAX_RETRIES:
        logger.info(
            "[RAG_TRANSFORM] Max retries reached (%d) — Serper failover for: %s",
            retry_count, rewritten[:80],
        )
        serper_memories: List[Dict] = []
        try:
            from kuro_backend.serper_tool import serper_search
            results = serper_search(rewritten, search_type="search", num_results=5)
            organic = results.get("organic", []) or []
            for r in organic[:5]:
                snippet = r.get("snippet", "")
                title = r.get("title", "")
                if snippet:
                    serper_memories.append({
                        "memory": f"[Web] {title}: {snippet}",
                        "source": "serper",
                    })
        except Exception as exc:
            logger.warning("[RAG_TRANSFORM] Serper failover failed: %s", exc)

        # Inject web results and unblock pipeline
        return {
            "mem0_retrieved_memories": serper_memories,
            "retrieval_grade": "relevant",    # unblock — best-effort web results
            "retrieval_retry_count": retry_count + 1,
            "rewritten_query": rewritten,
        }

    # ── LLM query rewrite ─────────────────────────────────────────────────────
    new_query = rewritten
    try:
        from kuro_backend.config import CLASSIFIER_MODEL
        client = _get_genai_client()

        prompt = (
            "You are an expert search query optimizer.\n\n"
            f"Original user question: {user_input}\n"
            f"Previous retrieval grade: {grade} (retrieval was not useful)\n\n"
            "Rewrite the question as a precise, specific search query that will "
            "retrieve better results from a personal AI memory system.\n"
            "Focus on key entities, topics, and temporal anchors.\n"
            "Return ONLY the rewritten query, no explanation."
        )
        resp = client.models.generate_content(
            model=CLASSIFIER_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=80,
            ),
        )
        new_query = (resp.text or "").strip() or user_input
    except Exception as exc:
        logger.warning("[RAG_TRANSFORM] Query rewrite failed: %s", exc)

    logger.info(
        "[RAG_TRANSFORM] retry=%d → rewritten query: %s",
        retry_count + 1, new_query[:80],
    )
    return {
        "rewritten_query": new_query,
        "retrieval_retry_count": retry_count + 1,
        # Reset grade so next retrieval gets re-evaluated
        "retrieval_grade": "ambiguous",
    }


# ── Auto-RAG Routing ──────────────────────────────────────────────────────────

def route_after_grader(state: KuroState) -> str:
    """
    Auto-RAG conditional edge after retrieval_grader_node.

    relevant   → attention_filter_node  (proceed with Natural Agency pipeline)
    ambiguous  → query_transform_node   (rewrite query, loop back)
    irrelevant → query_transform_node   (rewrite query, loop back)

    Loop is bounded by retrieval_retry_count via query_transform_node's
    Serper failover at _RAG_MAX_RETRIES.
    """
    grade = state.get("retrieval_grade", "ambiguous")
    if grade == "relevant":
        return "attention_filter_node"
    return "query_transform_node"


# ============================================
# NATURAL AGENCY TIER (Tomasello 2025) — V7.2
# Gated to: advisor, consultant, auditor personas only
# ============================================

_AGENCY_PERSONAS = {"advisor", "consultant", "auditor"}

# ── T1a: Attention / Relevance Filter ────────────────────────────────────────

def attention_filter_node(state: KuroState) -> Dict[str, Any]:
    """
    T1 Attention Gate: classifies input into intent categories.
    Fast heuristic + optional LLM classifier.

    Categories:
      dissertation  → core PhD novelty / methodology work
      research      → reading papers, referencing, analysis
      technical     → code, debugging, devops
      administrative→ file ops, scheduling, finance
      off_track     → diverges from dissertation goals (triggers inhibition)
      general       → everything else
    """
    persona_mode = state.get("persona_mode", "consultant")

    # Only run for agency personas — fast bypass for others.
    if persona_mode not in _AGENCY_PERSONAS:
        return {"_intent_category": "general"}

    user_input = (state.get("user_input") or "").lower()

    import re as _re
    _DISS = _re.compile(
        r"\b(novel|kontribusi|disertasi|dissertation|bab\s*\d|chapter\s*\d|"
        r"hipotesis|hypothesis|metodologi|methodology|forensic|phd|tesis|thesis|"
        r"eu ai act|uu pdp|nist|iso\s*\d+|research gap|evidence)\b", _re.I
    )
    _RESEARCH = _re.compile(
        r"\b(paper|artikel|article|jurnal|journal|referensi|reference|"
        r"analisis|analysis|ringkas|summarize|review|literatur|literature)\b", _re.I
    )
    _TECH = _re.compile(
        r"\b(kode|code|debug|error|bug|fix|refactor|deploy|server|"
        r"script|function|import|install|dependency)\b", _re.I
    )
    _ADMIN = _re.compile(
        r"\b(file|excel|export|budget|finance|jadwal|schedule|reminder)\b", _re.I
    )
    _OFF = _re.compile(
        r"\b(cerita|joke|lelucon|hiburan|entertainment|rehat|istirahat|"
        r"random|gaming|nonton|film|musik|music)\b", _re.I
    )

    if _DISS.search(user_input):
        category = "dissertation"
    elif _RESEARCH.search(user_input):
        category = "research"
    elif _TECH.search(user_input):
        category = "technical"
    elif _ADMIN.search(user_input):
        category = "administrative"
    elif _OFF.search(user_input):
        category = "off_track"
    else:
        category = "general"

    logger.info("[ATTENTION_FILTER] persona=%s category=%s", persona_mode, category)
    return {"_intent_category": category}


# ── T1b: Executive Monitor (Inhibit + Simulate) ───────────────────────────────

def executive_monitor_node(state: KuroState) -> Dict[str, Any]:
    """
    T1 Executive / Intentional Agent — Tomasello (2025).

    1. Inhibitory filter: withhold response for off-track/bloatware inputs
       when active persona is advisor/consultant/auditor.
    2. Imaginative simulation:
       - advisor/consultant → Draft A (Conservative) vs Draft B (Novel)
       - auditor           → Draft A (Pass/Safe)    vs Draft B (Adversarial/Fail)
    3. Cognitive effort: compute via kuro_backend.agency.cognitive_effort.
    """
    persona_mode = state.get("persona_mode", "consultant")

    if persona_mode not in _AGENCY_PERSONAS:
        return {
            "inhibited": False, "inhibition_reason": "",
            "simulated_outcomes": [], "selected_outcome": None,
            "cognitive_effort": "low",
        }

    user_input = state.get("user_input", "")
    intent_cat = state.get("_intent_category", "general")

    # ── 1. Inhibitory filter ─────────────────────────────────────────────────
    BLOATWARE_SIGNALS = [
        "tambahkan fitur", "buat animasi", "install plugin",
        "change theme", "add emoji", "redesign ui", "ganti warna",
    ]
    IMPULSIVE_SIGNALS = [
        "cerita", "joke", "lelucon", "hiburan", "random fact",
        "nonton", "gaming", "musik",
    ]
    lowered = user_input.lower()
    is_bloatware = any(s in lowered for s in BLOATWARE_SIGNALS)
    is_impulsive = intent_cat == "off_track" and any(
        s in lowered for s in IMPULSIVE_SIGNALS
    )

    if is_bloatware or is_impulsive:
        reason = (
            "Bloatware-type request detected — not backed by BRD." if is_bloatware
            else "Off-track impulsive input — diverges from dissertation goals."
        )
        logger.info("[EXECUTIVE] Inhibiting. persona=%s reason=%s", persona_mode, reason)
        return {
            "inhibited": True,
            "inhibition_reason": reason,
            "simulated_outcomes": [],
            "selected_outcome": None,
            "cognitive_effort": "low",
        }

    # ── 2. Imaginative simulation ────────────────────────────────────────────
    simulated_outcomes: List[Dict] = []
    selected_outcome: Optional[Dict] = None

    sim_eligible = intent_cat in ("dissertation", "research") or persona_mode == "auditor"

    if sim_eligible:
        try:
            from kuro_backend.config import CLASSIFIER_MODEL

            client = _get_genai_client()

            if persona_mode == "auditor":
                sim_prompt = (
                    f'You are a QA Architect auditor.\n'
                    f'Scenario: "{user_input}"\n\n'
                    f'Generate two audit simulation drafts.\n'
                    f'Draft A (Pass/Safe): The code/approach meets requirements — '
                    f'describe why it is safe and what tests pass.\n'
                    f'Draft B (Adversarial/Fail): The most dangerous failure scenario — '
                    f'edge cases, adversarial inputs, or missing controls that would cause failure.\n\n'
                    f'Return JSON: {{"draft_a": {{"strategy": "...", "adversarial_score": 0}}, '
                    f'"draft_b": {{"strategy": "...", "adversarial_score": 10}}}}\n'
                    f'adversarial_score: 0=safe, 10=critical failure found.'
                )
                score_key = "adversarial_score"
                # auditor always selects Draft B (the adversarial scenario) to surface risks
                pick_highest = True
            else:
                sim_prompt = (
                    f'You are a dissertation research planner.\n'
                    f'Question: "{user_input}"\n\n'
                    f'Generate two alternative response strategies.\n'
                    f'Draft A (Conservative): Safe, grounded answer aligned with existing literature.\n'
                    f'Draft B (Novel): Creative, potentially groundbreaking angle advancing novelty.\n\n'
                    f'Return JSON: {{"draft_a": {{"strategy": "...", "novelty_score": 3}}, '
                    f'"draft_b": {{"strategy": "...", "novelty_score": 8}}}}\n'
                    f'novelty_score: 0=very conventional, 10=highly novel.'
                )
                score_key = "novelty_score"
                pick_highest = True  # advisor/consultant pick highest novelty

            resp = client.models.generate_content(
                model=CLASSIFIER_MODEL,
                contents=sim_prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=350,
                    response_mime_type="application/json",
                ),
            )
            sim_data = json.loads(resp.text or "{}")
            draft_a = {"label": "Draft A", **sim_data.get("draft_a", {})}
            draft_b = {"label": "Draft B", **sim_data.get("draft_b", {})}
            simulated_outcomes = [draft_a, draft_b]
            selected_outcome = max(
                simulated_outcomes,
                key=lambda d: int(d.get(score_key, 0)),
            ) if pick_highest else draft_a
            logger.info(
                "[EXECUTIVE] Simulation done. Selected=%s score=%s",
                selected_outcome.get("label"),
                selected_outcome.get(score_key),
            )
        except Exception as exc:
            logger.warning("[EXECUTIVE] Simulation failed: %s", exc)

    # ── 3. Cognitive effort ──────────────────────────────────────────────────
    from kuro_backend.agency.cognitive_effort import compute as _compute_effort
    effort = _compute_effort(intent_cat, user_input)

    return {
        "inhibited": False,
        "inhibition_reason": "",
        "simulated_outcomes": simulated_outcomes,
        "selected_outcome": selected_outcome,
        "cognitive_effort": effort,
    }


# ── T2: Metacognitive Review (Belief Revision) ────────────────────────────────

def metacognitive_review_node(state: KuroState) -> Dict[str, Any]:
    """
    T2 Rational / Metacognitive Agent — Tomasello (2025).

    1. Belief Revision: compare current input against prior BRD commitments
       (research_ledger) via memory_coordinator.evaluate_alignment().
    2. Evidence Quality: incorporate retrieval_grade from Auto-RAG — if beliefs
       conflict AND retrieval was poor-quality, the reflective message flags the
       double uncertainty (belief conflict + weak evidence backing).
    3. Contradiction Trigger: if conflict score < threshold, set
       metacognitive_flag=True and produce a reflective realignment message.
    4. Joint Goal Injection: on aligned path, inject joint_goal_block for
       response_node to embed in system prompt (T3 Shared Agency).
    """
    persona_mode = state.get("persona_mode", "consultant")

    if persona_mode not in _AGENCY_PERSONAS:
        return {
            "alignment_score": 1.0,
            "metacognitive_flag": False,
            "joint_goal_block": "",
        }

    # If the Executive already inhibited — skip metacognitive check.
    if state.get("inhibited"):
        return {
            "alignment_score": 1.0,
            "metacognitive_flag": False,
            "joint_goal_block": "",
        }

    user_input = state.get("user_input", "")

    # ── 1. Belief Revision ───────────────────────────────────────────────────
    alignment_result: Dict[str, Any] = {
        "score": 1.0, "conflicts": [], "supports": [], "recommendation": "",
    }
    username = state.get("username", "Pantronux")
    try:
        alignment_result = memory_coordinator.evaluate_alignment(user_input, persona_mode, username=username)
    except Exception as exc:
        logger.warning("[METACOGNITIVE] evaluate_alignment error for %s: %s", username, exc)

    score = float(alignment_result.get("score", 1.0))
    threshold = float(os.getenv("KURO_ALIGNMENT_THRESHOLD", "0.35"))

    # ── 2. Evidence Quality (Auto-RAG integration) ───────────────────────────
    retrieval_grade = state.get("retrieval_grade", "relevant")
    retry_count = state.get("retrieval_retry_count", 0)
    evidence_weak = retrieval_grade in ("irrelevant", "ambiguous")
    evidence_note = ""
    if evidence_weak:
        evidence_note = (
            f"\n\n> ⚠️ **Evidence Note:** Retrieval memory shows `{retrieval_grade}` quality "
            f"after {retry_count} attempts — response may be less supported by long-term memory evidence."
        )

    # ── 3. Contradiction Trigger ─────────────────────────────────────────────
    if score < threshold:
        conflicts = alignment_result.get("conflicts", [])
        conflict_txt = "; ".join(str(c) for c in conflicts[:3]) or "Input diverges from prior BRD goals."
        rec = alignment_result.get("recommendation", "Realign with dissertation objective.")
        reflective_msg = (
            f"⚠️ **[Metacognitive Alignment Check — T2 Rational Agent]**\n\n"
            f"Master Pantronux, before continuing — I have detected a potential conflict "
            f"between the current instructions and our mutually agreed-upon dissertation commitments.\n\n"
            f"**Conflict detected:**\n{conflict_txt}\n\n"
            f"**Recommendation:** {rec}"
            f"{evidence_note}\n\n"
            f"Would you like to proceed with this realignment in mind? "
            f"Or is there any new context I need to understand before continuing?"
        )
        logger.info(
            "[METACOGNITIVE] Conflict detected score=%.2f retrieval=%s → reflective path",
            score, retrieval_grade,
        )
        return {
            "alignment_score": score,
            "metacognitive_flag": True,
            "final_response": reflective_msg,
            "joint_goal_block": "",
        }

    # ── 4. Joint Goal Injection (T3) ─────────────────────────────────────────
    joint_goal_block = ""
    try:
        from kuro_backend.agency.joint_goal_store import format_for_prompt
        joint_goal_block = format_for_prompt(username=username)
    except Exception as exc:
        logger.debug("[METACOGNITIVE] joint_goal_block skipped: %s", exc)

    return {
        "alignment_score": score,
        "metacognitive_flag": False,
        "joint_goal_block": joint_goal_block,
    }



# ── T2 Reflective Response (Metacognitive message passthrough) ────────────────

def reflective_response_node(state: KuroState) -> Dict[str, Any]:
    """
    Only reached when metacognitive_flag=True OR inhibited=True.
    The reflective message is already assembled in state['final_response']
    by metacognitive_review_node or the Executive inhibition path.
    This node simply ensures memory persistence is skipped for inhibited turns.
    """
    # Build inhibition message if Executive withheld response
    if state.get("inhibited"):
        reason = state.get("inhibition_reason", "Prepotent response withheld.")
        msg = (
            f"⚡ **[Executive Monitor — T1 Intentional Agent]**\n\n"
            f"Master Pantronux, respons ini ditahan oleh Executive Monitor.\n\n"
            f"**Alasan:** {reason}\n\n"
            f"Mohon arahkan kembali ke tujuan disertasi kita. "
            f"Jika ini memang diperlukan, gunakan persona yang sesuai (chill/tactical)."
        )
        return {"final_response": msg}

    # Metacognitive reflective message already in final_response — pass through.
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
        username = state.get("username", "Pantronux")
        ctx = memory_coordinator.build_context_for_llm(
            user_input,
            persona_mode,
            mem0_retrieved_memories=mem0_memories or None,
            session_id=session_id,
            username=username,
        )
        memory_injection = ctx["memory_injection"]
        mem0_context_block = ctx.get("mem0_context_block")
        referent_block = ctx.get("referent_grounding_block")
        context_budget = ctx.get("budget")

        # Build system prompt
        master_name = state.get("master_name", "Pantronux")
        system_prompt = get_system_instruction(persona_override=persona_mode, master_name=master_name)
        
        intent = state.get("_intent", "new")
        if intent == "edit":
            # Extract last assistant message for continuity lock
            last_assistant_message = ""
            recent_msgs = ctx.get("recent_messages", [])
            for msg in reversed(recent_msgs):
                if msg.get("role") == "assistant":
                    last_assistant_message = msg.get("content", "")
                    break

            continuity_block = (
                "\n\n[TASK CONTINUITY LOCK - EDIT MODE]\n"
                "The Master is editing, revising, or adding to the previous turn. "
                "You MUST act as an incremental update to the existing state. "
                "DO NOT generate a 'New Conclusion' or restart the thought process. "
                "Maintain the exact same context and only apply the requested delta."
            )

            if last_assistant_message:
                # Truncate to reasonable length to avoid overwhelming context
                preview_len = min(len(last_assistant_message), 3000)
                continuity_block += (
                    f"\n\n[LAST GENERATED OUTPUT TO MODIFY]\n"
                    f"{last_assistant_message[:preview_len]}"
                    f"{'...' if len(last_assistant_message) > preview_len else ''}"
                )

            system_prompt += continuity_block

        # ── T2/T3 Natural Agency injections ──────────────────────────────────
        # 1. Joint Goal Block (T3 Shared Agency) — active commitments
        joint_goal_block = state.get("joint_goal_block") or ""
        if joint_goal_block:
            system_prompt += f"\n\n{joint_goal_block}"

        # 2. Cognitive Effort CoT (T2 Metacognitive) — reasoning depth scaler
        effort = state.get("cognitive_effort") or "low"
        try:
            from kuro_backend.agency.cognitive_effort import get_cot_injection
            cot_inj = get_cot_injection(effort)
            if cot_inj:
                system_prompt += cot_inj
        except Exception as _cot_exc:
            logger.debug("[RESPONSE_NODE] cognitive_effort CoT skipped: %s", _cot_exc)

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

        # ── T1 Simulation hint (Executive selected_outcome) ───────────────────
        selected_outcome = state.get("selected_outcome")
        if selected_outcome and selected_outcome.get("strategy"):
            label = selected_outcome.get("label", "Simulation")
            strategy = selected_outcome["strategy"]
            sections["simulation_hint"] = (
                f"\n\n[EXECUTIVE SIMULATION — {label}]\n"
                f"Recommended approach: {strategy}\n"
                f"Incorporate this strategic direction into your response."
            )

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

        # Generate response using direct google-genai SDK (more reliable)
        response_text: Optional[str] = None  # Initialize to detect if generation fails
        try:
            genai_client = _get_genai_client()

            profile = personas.get_sampling_profile(persona_mode)

            # Use cached content if configured
            config_kwargs = {
                "system_instruction": system_prompt,
                "temperature": profile.temperature,
                "top_p": profile.top_p,
                "top_k": profile.top_k,
                "tools": [{"google_search": {}}],
            }
            if settings.GEMINI_CACHED_CONTENT:
                config_kwargs["cached_content"] = settings.GEMINI_CACHED_CONTENT

            response = genai_client.models.generate_content(
                model=PRIMARY_MODEL,
                contents=contents_parts,
                config=genai_types.GenerateContentConfig(**config_kwargs),
            )
            
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
            
            # Track token usage
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                prompt_tokens = response.usage_metadata.prompt_token_count or 0
                completion_tokens = response.usage_metadata.candidates_token_count or 0
                total_tokens = response.usage_metadata.total_token_count or (prompt_tokens + completion_tokens)
                
                username = state.get("username", "Pantronux")
                observability.track_token_usage(session_id, prompt_tokens, completion_tokens, total_tokens, username=username)
                
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
        username = state.get("username", "Pantronux")
        _persist_short_term_and_enqueue_writes(user_input, response_text, persona_mode, username)

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
            if not function_calls:
                reason = ""
                try:
                    reason = (response.text or "").strip()[:200]
                except Exception:
                    reason = ""
                logger.info("[TOOL_NODE] No function_call returned; falling through.")
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
    if next_step == END:
        return "__end__"
    return next_step


def route_after_executive(state: KuroState) -> str:
    """
    T1 Exit Gate: if inhibited, go directly to reflective_response_node
    (skipping metacognitive check — no point reviewing an inhibited input).
    Otherwise continue to metacognitive_review_node.
    """
    if state.get("inhibited"):
        return "reflective_response_node"
    return "metacognitive_review_node"


def route_after_metacognitive(state: KuroState) -> str:
    """
    T2 Exit Gate:
    - metacognitive_flag → reflective_response_node (realignment message)
    - next_step==tool_node → tool_node
    - default → response_node
    """
    if state.get("metacognitive_flag"):
        return "reflective_response_node"
    next_step = state.get("next_step", "response_node")
    if next_step == "tool_node":
        return "tool_node"
    return "response_node"


# ============================================
# GRAPH CONSTRUCTION
# ============================================

def build_kuro_graph() -> StateGraph:
    """
    Build the Kuro LangGraph state machine.

    V7.2.1 Auto-RAG + Natural Agency Graph Structure:
    START
      → reflection_node             (edit/new intent)
      → supervisor_node             (tool vs response routing)
      → memory_retrieval_node       (Mem0 prefetch; uses rewritten_query on retry)
      → retrieval_grader_node       (CRAG: relevant | ambiguous | irrelevant)
          ├── [relevant]   → attention_filter_node
          └── [non-relevant] → query_transform_node
                                 ├── [retry<max] → memory_retrieval_node (LOOP)
                                 └── [retry==max] → Serper failover → attention_filter_node
      → attention_filter_node       (T1a: intent category)
      → executive_monitor_node      (T1b: inhibit + A/B simulate)
          ├── [inhibited]  → reflective_response_node
          └── [ok]         → metacognitive_review_node
                               ├── [conflict] → reflective_response_node
                               └── [aligned]  → tool_node | response_node
      → memory_extraction_node → END

    Loop safety: query_transform_node self-terminates at _RAG_MAX_RETRIES=2
    by injecting Serper results and forcing retrieval_grade='relevant'.
    """
    checkpointer = MemorySaver()
    graph_builder = StateGraph(KuroState)

    # ── Core nodes ────────────────────────────────────────────────────────────
    graph_builder.add_node("reflection_node", reflection_node)
    graph_builder.add_node("supervisor_node", supervisor_node)
    graph_builder.add_node("memory_retrieval_node", memory_retrieval_node)
    graph_builder.add_node("tool_node", tool_node)
    graph_builder.add_node("response_node", response_node)
    graph_builder.add_node("memory_extraction_node", memory_extraction_node)

    # ── Auto-RAG nodes (V7.2.1) ───────────────────────────────────────────────
    graph_builder.add_node("retrieval_grader_node", retrieval_grader_node)
    graph_builder.add_node("query_transform_node", query_transform_node)

    # ── Natural Agency nodes (V7.2) ───────────────────────────────────────────
    graph_builder.add_node("attention_filter_node", attention_filter_node)
    graph_builder.add_node("executive_monitor_node", executive_monitor_node)
    graph_builder.add_node("metacognitive_review_node", metacognitive_review_node)
    graph_builder.add_node("reflective_response_node", reflective_response_node)

    # ── Edges: entry → retrieval ──────────────────────────────────────────────
    graph_builder.add_edge(START, "reflection_node")
    graph_builder.add_edge("reflection_node", "supervisor_node")
    graph_builder.add_edge("supervisor_node", "memory_retrieval_node")

    # ── Auto-RAG loop: retrieval → grade → [loop|continue] ───────────────────
    graph_builder.add_edge("memory_retrieval_node", "retrieval_grader_node")
    graph_builder.add_conditional_edges(
        "retrieval_grader_node",
        route_after_grader,
        {
            "attention_filter_node": "attention_filter_node",
            "query_transform_node": "query_transform_node",
        },
    )
    # query_transform loops back to retrieval (uses rewritten_query)
    # The loop terminates via Serper failover inside query_transform_node
    # which forces retrieval_grade='relevant' → next grader pass exits to attention_filter
    graph_builder.add_edge("query_transform_node", "memory_retrieval_node")

    # ── Natural Agency pipeline ───────────────────────────────────────────────
    graph_builder.add_edge("attention_filter_node", "executive_monitor_node")

    graph_builder.add_conditional_edges(
        "executive_monitor_node",
        route_after_executive,
        {
            "reflective_response_node": "reflective_response_node",
            "metacognitive_review_node": "metacognitive_review_node",
        },
    )
    graph_builder.add_conditional_edges(
        "metacognitive_review_node",
        route_after_metacognitive,
        {
            "reflective_response_node": "reflective_response_node",
            "tool_node": "tool_node",
            "response_node": "response_node",
        },
    )

    # ── Tail edges ────────────────────────────────────────────────────────────
    graph_builder.add_edge("reflective_response_node", "memory_extraction_node")
    graph_builder.add_edge("tool_node", "response_node")
    graph_builder.add_edge("response_node", "memory_extraction_node")
    graph_builder.add_edge("memory_extraction_node", END)

    graph = graph_builder.compile(checkpointer=checkpointer)
    logger.info("[LANGGRAPH] V7.2.1 Auto-RAG + Natural Agency graph compiled successfully.")
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
    session_id: Optional[str] = None,
    master_name: str = "Pantronux",
    username: str = "Pantronux",
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
    if session_id is None:
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
                    _persist_short_term_and_enqueue_writes(message, cached_response, persona_mode, username)
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
                session_id=session_id,
                username=username,
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
            system_prompt = get_system_instruction(persona_override=persona_mode, master_name=master_name)

            # Re-evaluate reflection node logic for fastpath
            intent = reflection_node({"user_input": message}).get("_intent", "new")
            if intent == "edit":
                last_assistant_message = ""
                recent_msgs = ctx.get("recent_messages", [])
                for msg in reversed(recent_msgs):
                    if msg.get("role") == "assistant":
                        last_assistant_message = msg.get("content", "")
                        break

                continuity_block = (
                    "\n\n[TASK CONTINUITY LOCK - EDIT MODE]\n"
                    "The Master is editing, revising, or adding to the previous turn. "
                    "You MUST act as an incremental update to the existing state. "
                    "DO NOT generate a 'New Conclusion' or restart the thought process. "
                    "Maintain the exact same context and only apply the requested delta."
                )

                if last_assistant_message:
                    preview_len = min(len(last_assistant_message), 3000)
                    continuity_block += (
                        f"\n\n[LAST GENERATED OUTPUT TO MODIFY]\n"
                        f"{last_assistant_message[:preview_len]}"
                        f"{'...' if len(last_assistant_message) > preview_len else ''}"
                    )

                system_prompt += continuity_block

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
            _persist_short_term_and_enqueue_writes(message, response_text, persona_mode, username)

            # V7.2.1 Mem0 Check inside streaming fast-path
            if intent != "edit":
                task_success = False
                success_keywords = ["thanks", "terima kasih", "selesai", "fixed", "done", "berhasil", "sip", "ok", "confirmed"]
                if any(kw in message.lower() for kw in success_keywords):
                    task_success = True

                if task_success:
                    _enqueue_post_response_task({
                        "kind": "mem0_extract",
                        "user_input": message,
                        "final_response": response_text,
                        "username": username,
                    })

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
            "master_name": master_name,
            "_session_id": session_id,
            "_approval_scope": approval_scope,
            "_trace_id": trace_id,
            # Natural Agency defaults (V7.2)
            "_intent_category": "general",
            "inhibited": False,
            "inhibition_reason": "",
            "simulated_outcomes": [],
            "selected_outcome": None,
            "cognitive_effort": "low",
            "alignment_score": 1.0,
            "metacognitive_flag": False,
            "joint_goal_block": "",
            # Auto-RAG defaults (V7.2.1)
            "retrieval_grade": "relevant",
            "retrieval_retry_count": 0,
            "rewritten_query": "",
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
                f"Maaf, {master_name}. Respons model kosong setelah pemeriksaan. Silakan ulangi pertanyaan."
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
        error_msg = f"Maaf, {master_name}. Terjadi kesalahan saat memproses permintaan Anda."
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
    session_id: Optional[str] = None,
    master_name: str = "Pantronux",
    username: str = "Pantronux",
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
    if session_id is None:
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
                    _persist_short_term_and_enqueue_writes(message, cached_response, persona_mode, username)
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
            "_session_id": session_id,
            "master_name": master_name,
            "username": username,
            "_approval_scope": approval_scope,
            "_trace_id": trace_id,
            # Natural Agency defaults (V7.2)
            "_intent_category": "general",
            "inhibited": False,
            "inhibition_reason": "",
            "simulated_outcomes": [],
            "selected_outcome": None,
            "cognitive_effort": "low",
            "alignment_score": 1.0,
            "metacognitive_flag": False,
            "joint_goal_block": "",
            # Auto-RAG defaults (V7.2.1)
            "retrieval_grade": "relevant",
            "retrieval_retry_count": 0,
            "rewritten_query": "",
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
