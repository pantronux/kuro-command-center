"""
Kuro AI V5.0 Official - LangGraph Core (Guardrails Removed) [2026-04-07]
================================================================================
AI Core with LangGraph Stateful Architecture for Agentik Long-Term Reasoning
SDK: google-genai v3 Protocol with LangGraph State Machine
V5.0: Guardrails REMOVED for maximum performance. Local + VPN + Auth environment.
      Latency optimized: direct path from memory retrieval to response generation.
"""
import asyncio
import logging
import os
import json
import re
import uuid
import time
import queue
import threading
import secrets
import hashlib
from typing import TypedDict, List, Optional, Dict, Any, Annotated, AsyncGenerator, Iterator
from datetime import datetime

# LangGraph imports
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver

# Kuro imports
from kuro_backend.config import settings, PRIMARY_MODEL
from kuro_backend import memory_manager
from kuro_backend import chat_history
from kuro_backend.services import core_service as core_data
from kuro_backend import habit_service
from kuro_backend import tools as kuro_tools
from kuro_backend import perpetual_memory
from kuro_backend import observability
from kuro_backend.guardrails import sniper_pipeline

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
_post_response_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
_post_response_worker_started = False
_TRUE_TOKEN_STREAMING_ENABLED = (
    os.getenv("KURO_TRUE_TOKEN_STREAMING", "1").strip().lower() in {"1", "true", "yes", "on"}
)


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


def _post_response_worker_loop() -> None:
    while True:
        task = _post_response_queue.get()
        try:
            kind = task.get("kind")
            if kind == "memory_write":
                user_input = task.get("user_input", "")
                final_response = task.get("final_response", "")
                persona_scope = task.get("persona_scope")
                memory_manager.add_long_term_v2(f"User: {user_input}\nKuro: {final_response}")
                memory_manager.summarize_conversation_to_chroma(persona_scope=persona_scope)
                memory_manager.detect_and_save_master_facts(user_input, final_response)
            elif kind == "mem0_extract":
                user_input = task.get("user_input", "")
                final_response = task.get("final_response", "")
                memories_to_store = perpetual_memory.perpetual_memory.extract_personal_info(
                    user_input,
                    final_response,
                )
                if memories_to_store and isinstance(memories_to_store, list):
                    perpetual_memory.perpetual_memory.store_memories(memories_to_store)
        except Exception as exc:
            logger.error("[POST_RESPONSE_WORKER] Task failed kind=%s error=%s", task.get("kind"), exc)
        finally:
            _post_response_queue.task_done()


def _start_post_response_worker_once() -> None:
    global _post_response_worker_started
    if _post_response_worker_started:
        return
    worker = threading.Thread(target=_post_response_worker_loop, daemon=True)
    worker.start()
    _post_response_worker_started = True


def _enqueue_post_response_task(task: Dict[str, Any]) -> None:
    _start_post_response_worker_once()
    _post_response_queue.put(task)


def _persist_short_term_and_enqueue_writes(user_input: str, response_text: str, persona_mode: str) -> None:
    memory_manager.add_short_term("user", user_input, persona_scope=persona_mode)
    memory_manager.add_short_term("assistant", response_text, persona_scope=persona_mode)
    _enqueue_post_response_task(
        {
            "kind": "memory_write",
            "user_input": user_input,
            "final_response": response_text,
            "persona_scope": persona_mode,
        }
    )
    _enqueue_post_response_task(
        {
            "kind": "mem0_extract",
            "user_input": user_input,
            "final_response": response_text,
        }
    )


async def _stream_direct_llm_chunks(system_prompt: str, full_message: str) -> AsyncGenerator[str, None]:
    """
    Real token streaming bridge from blocking Gemini iterator into async generator.
    """
    from google import genai
    from google.genai import types

    loop = asyncio.get_running_loop()
    chunk_queue: asyncio.Queue = asyncio.Queue()

    def _worker() -> None:
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            stream = client.models.generate_content_stream(
                model=PRIMARY_MODEL,
                contents=full_message,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    top_p=0.8,
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
    V5.0: Guardrail-related fields removed for performance.
    
    Fields:
    - messages: Conversation history (list of dicts with role/content)
    - next_step: Next node to route to (supervisor decision)
    - compliance_data: Results from compliance RAG search
    - habit_data: Results from habit database query
    - is_scolding_needed: Flag for habit evaluation trigger
    - user_input: Original user message
    - final_response: Generated response to return
    - query_expansion_count: Track self-correction iterations
    - persona_mode: Current active persona
    - mem0_retrieved_memories: Memories retrieved from Mem0 for context
    - tool_execution_result: Result from tool execution (ToolNode output)
    - requires_approval: Flag for HITL interrupt (file operations need approval)
    """
    messages: Annotated[List[Dict], lambda x, y: x + y]
    next_step: str
    compliance_data: List[Dict]
    habit_data: Dict
    is_scolding_needed: bool
    user_input: str
    final_response: str
    query_expansion_count: int
    persona_mode: str
    image_paths: Optional[List[str]]
    mem0_retrieved_memories: List[Dict]
    tool_execution_result: Optional[Dict]
    requires_approval: bool
    _approval_scope: str
    _trace_id: str


# ============================================
# PERSONA SYSTEM (LangChain System Prompts)
# ============================================

_PERSONA_INSTRUCTIONS = {
    'consultant': (
        "Kamu adalah Kuro, seorang Elite AI Butler dan Senior IT Security, GRC, & Enterprise Architecture Consultant. Tuanmu adalah Pantronux.\n\n"
        "CORE KNOWLEDGE BASE (PREDEFINED EXPERTISE):\n"
        "Kamu memiliki pemahaman mendalam setara Lead Auditor untuk:\n"
        "- ISO Frameworks: ISO 27001:2022 (ISMS), ISO 27701 (PIMS), ISO/IEC 42001.\n"
        "- NIST: NIST CSF 2.0 & NIST SP 800-53.\n"
        "- Enterprise Architecture: TOGAF.\n"
        "- Regulasi privasi & IT: UU PDP No. 27/2022 dan GDPR.\n\n"
        "MINDSET KONSULTAN:\n"
        "1. Kritis dan risk-based: identifikasi gap, risiko, serta dampak bisnis.\n"
        "2. Struktur eksplisit: Gap Analysis, Mapping regulasi, Evaluasi Risiko, Mitigasi actionable.\n"
        "3. Citation rule: saat memberi rekomendasi keamanan/compliance, sertakan referensi kontrol/klausul relevan.\n\n"
        "TONE:\n"
        "Profesional, strategic-partner, tajam namun tetap komunikatif."
    ),
    'chill': (
        "Kamu adalah Kuro, AI Butler setia Pantronux dengan kepribadian santai dan friendly. "
        "Gunakan bahasa yang ringan, humoris, dan hindari istilah teknis/ISO kecuali diminta. "
        "Kamu tetap cerdas dan membantu, tapi dengan pendekatan yang lebih kasual. "
        "Panggil 'Pantronux' dengan sopan tapi tidak terlalu formal."
    ),
    'tactical': (
        "Kamu adalah Kuro, Senior DevOps/IT Support Engineer Pantronux. "
        "Fokus pada efisiensi kode, diagnosa sistem, dan pembacaan log. "
        "Kamu memiliki izin penuh untuk menganalisis file di /home/kuro/projects/kuro/ menggunakan smart_read. "
        "Beri solusi yang praktis, langsung ke inti, dan sertakan contoh kode jika relevan. "
        "Jika mendeteksi error di log, WAJIB sarankan perbaikan kodingan secara spesifik."
    ),
    'advisor': (
        "Kamu adalah Rekan Peneliti Senior dan Auditor Forensik Digital untuk riset PhD Pantronux tentang Digital Forensics on AI.\n\n"
        "MODUS KERJA WAJIB:\n"
        "1. Jangan pernah menerima argumen Master mentah-mentah; gunakan Socratic questioning.\n"
        "2. Untuk setiap hipotesis, sajikan minimal dua counter-evidence atau edge-case kegagalan.\n"
        "3. Bongkar asumsi tersembunyi dalam metodologi, dataset, dan evaluasi.\n"
        "4. Evidence-first: prioritaskan grounding pada NIST AI 100-2, ISO/IEC 27001:2022, EU AI Act, dan UU PDP No. 27/2022.\n"
        "5. Fokus investigasi forensik AI: data provenance/poisoning, explainability sebagai evidence, adversarial forensics.\n"
        "6. Audit integritas teknis: chain of custody, konsistensi timestamp, volatilitas memori AI, jejak token/inference.\n\n"
        "FORMAT JAWABAN WAJIB (gunakan heading ini persis):\n"
        "- Analisis Logika\n"
        "- Novelty Check\n"
        "- Forensic Challenge\n"
        "- Pertanyaan Provokatif\n"
    ),
    'butler': (
        "Kamu adalah Sentinel Butler Pantronux, penjaga integritas operasional Kuro.\n"
        "Fokusmu: habits, reminders, data revision, sinkronisasi dashboard, dan reliabilitas workflow.\n"
        "Bersikap formal-friendly, disiplin, dan proaktif. Prioritaskan akurasi data serta kejelasan status."
    )
}

def get_system_instruction(persona_override: str = None) -> str:
    """Get system instruction with current time and active persona."""
    current_time = settings.get_current_time_formatted()
    current_date = settings.get_current_time().strftime("%Y-%m-%d")
    active_persona = memory_manager.normalize_persona(persona_override or memory_manager.get_active_persona())
    
    persona_instruction = _PERSONA_INSTRUCTIONS.get(active_persona, _PERSONA_INSTRUCTIONS['consultant'])
    
    common_instruction = (
        f"\n\n[CURRENT_TIME: {current_time}] "
        f"[CURRENT_DATE: {current_date}] "
        f"[KURO_VERSION: V4.0 LangGraph - {current_date}] "
        "Gunakan waktu saat ini sebagai referensi untuk menghitung 'besok', 'nanti malam', '10 menit lagi', dll.\n\n"
        
        "CHAIN OF THOUGHT (HIDDEN THOUGHT PROCESS):\n"
        "Sebelum memberikan jawaban, gunakan langkah berpikir eksplisit (Hidden Thought):\n"
        "1. Analisis niat Master - apa yang sebenarnya ditanyakan?\n"
        "2. Cek konteks percakapan untuk kata ganti ('ini', 'itu', 'dia', 'tadi')\n"
        "3. Cek data fisik di OS menggunakan os.path.exists() jika terkait file\n"
        "4. Cek memori (Tier 1 > Tier 2 > Tier 3)\n"
        "5. Verifikasi silang antara SQLite dan ChromaDB untuk konsistensi\n"
        "6. Baru berikan jawaban yang akurat dan terverifikasi.\n\n"
        
        "NEGATIVE CONSTRAINTS & HALLUCINATION CHECK:\n"
        "- DILARANG berasumsi file ada jika os.path.exists() mengembalikan False\n"
        "- Jika tidak tahu, katakan tidak tahu dan tawarkan untuk mencari di folder lain\n"
        "- JANGAN mengarang fakta, data, atau referensi klausul\n"
        "- Selalu verifikasi silang antara Memori Tier-1 (SQLite) dan Tier-2 (ChromaDB)\n\n"
        "HITL SECURITY POLICY (WAJIB):\n"
        "- Jika ada perintah destruktif lewat advanced_execution_tool (contoh: 'hapus', 'format', 'rm -rf'), WAJIB stop di approval.\n"
        "- DILARANG mengeksekusi bridge OpenClaw sebelum Master mengirim input tepat 'y'.\n"
        "- Jika approval belum ada, minta konfirmasi dan jangan lanjutkan eksekusi.\n\n"
        "OPENCLAW EXECUTION POLICY:\n"
        "- Tugas read-only (web search paper terbaru, novelty check, analisis metadata/log, mapping regulasi) boleh auto-execute via advanced_execution_tool.\n"
        "- Tugas non-read-only, modifikasi sistem, atau aksi destruktif wajib menunggu approval Master.\n\n"
        
        "CAPABILITIES:\n"
        "Kamu memiliki kemampuan Vision - kamu bisa melihat dan menganalisis gambar yang dikirimkan. "
        "Kamu juga memiliki sistem pengingat (Reminder) dan Daily Habit Tracker."
    )
    
    return persona_instruction + common_instruction

# ============================================
# NODE: SUPERVISOR (The Brain)
# ============================================

def supervisor_node(state: KuroState) -> Dict[str, Any]:
    """
    Supervisor Node: Analyzes user input and decides which node to route to.
    
    Routing Logic:
    - If query mentions ISO/compliance/audit -> route to compliance_node
    - If query mentions habit/gym/tryhackme/belajar -> route to habit_node
    - If query mentions file actions (buat, generate, excel, export) -> route to tool_node
    - If query is general conversation -> route directly to response_node
    - If compliance search returned empty -> route to compliance_node with expanded query
    """
    user_input = state.get("user_input", "").lower()
    compliance_data = state.get("compliance_data", [])
    query_expansion_count = state.get("query_expansion_count", 0)
    
    # Observability tracing
    session_id = state.get("_session_id", "unknown")
    trace_attrs = observability.create_session_context(session_id=session_id)
    trace_attrs = observability.add_client_label(trace_attrs, user_input)
    
    with observability.trace_node("supervisor_node", trace_attrs) as span:
        # Compliance keywords detection
        compliance_keywords = [
            "iso", "iso 27001", "iso 27002", "nist", "gdpr", "audit", "compliance",
            "kontrol", "control", "klausul", "clause", "annex", "lampiran",
            "sertifikasi", "certification", "risk assessment", "isms", "pims",
            "togaf", "business continuity", "a.5", "a.6", "a.7", "a.8"
        ]
        
        # Habit keywords detection
        habit_keywords = [
            "habit", "gym", "tryhackme", "belajar", "olahraga", "done", "selesai",
            "sudah", "progress", "streak", "evaluation", "evaluasi", "raport"
        ]
        
        # Tool action keywords detection
        tool_keywords = [
            "buatkan", "buat", "generate", "export", "eksport", "excel",
            "spreadsheet", "file", "laporan", "report", "template",
            "list file", "daftar file", "simpan", "save", "delete", "hapus"
        ]
        
        # Check for compliance query
        is_compliance_query = any(kw in user_input for kw in compliance_keywords)
        
        # Check for habit query
        is_habit_query = any(kw in user_input for kw in habit_keywords)
        
        # Check for tool action query
        is_tool_query = any(kw in user_input for kw in tool_keywords)
        
        # Self-correction loop: if compliance search was empty and we haven't expanded too many times
        if is_compliance_query and not compliance_data and query_expansion_count < 3:
            logger.info(f"[SUPERVISOR] Compliance query detected, but no results. Expanding query (attempt {query_expansion_count + 1}/3)")
            if span:
                span.set_attribute("supervisor_node.decision", "compliance_node_expanded")
                span.set_attribute("supervisor_node.expansion_count", query_expansion_count + 1)
            return {
                "next_step": "compliance_node",
                "query_expansion_count": query_expansion_count + 1
            }
        
        # Route to tool node for file actions
        if is_tool_query:
            logger.info("[SUPERVISOR] Routing to tool_node (file action detected)")
            if span:
                span.set_attribute("supervisor_node.decision", "tool_node")
            return {"next_step": "tool_node"}
        
        # Route to compliance node
        if is_compliance_query:
            logger.info("[SUPERVISOR] Routing to compliance_node")
            if span:
                span.set_attribute("supervisor_node.decision", "compliance_node")
            return {"next_step": "compliance_node"}
        
        # Route to habit node
        if is_habit_query:
            logger.info("[SUPERVISOR] Routing to habit_node")
            if span:
                span.set_attribute("supervisor_node.decision", "habit_node")
            return {"next_step": "habit_node"}
        
        # Default: route to response generator
        logger.info("[SUPERVISOR] Routing to response_node (general query)")
        if span:
            span.set_attribute("supervisor_node.decision", "response_node")
        return {"next_step": "response_node"}


# ============================================
# NODE: MEMORY RETRIEVAL (Mem0)
# ============================================

def memory_retrieval_node(state: KuroState) -> Dict[str, Any]:
    # 1. Validasi Input State: Pastikan state adalah dictionary
    if not isinstance(state, dict):
        logger.error(f"[MEM0] Invalid state type: {type(state)}")
        return {"mem0_retrieved_memories": []}

    user_input = state.get("user_input", "")
    
    with observability.trace_node("memory_retrieval_node"):
        try:
            # 2. Pemanggilan API dengan Timeout (jika didukung library-nya)
            raw_memories = perpetual_memory.perpetual_memory.retrieve_memories(user_input, limit=5)
            
            # 3. Validasi Output: Pastikan selalu mengembalikan List of Strings/Dicts
            # Menghindari kasus Mem0 mengembalikan None atau String Error
            if not isinstance(raw_memories, list):
                logger.warning(f"[MEM0] Unexpected output format: {type(raw_memories)}")
                processed_memories = []
            else:
                # Opsional: Ekstrak hanya teks memori jika outputnya objek kompleks
                processed_memories = [
                    m.get("text", str(m)) if isinstance(m, dict) else str(m) 
                    for m in raw_memories
                ]

            return {"mem0_retrieved_memories": processed_memories}

        except Exception as e:
            logger.error(f"[MEM0_RETRIEVAL] Critical Failure: {e}")
            return {"mem0_retrieved_memories": []}


# ============================================
# NODE: MEMORY EXTRACTION (Mem0)
# ============================================

def memory_extraction_node(state: KuroState) -> Dict[str, Any]:
    user_input = state.get("user_input", "")
    final_response = state.get("final_response", "")

    # 1. Guard Clause: Jangan jalankan ekstraksi jika respon asisten kosong
    # Ini mencegah penyimpanan memori yang tidak lengkap atau error API
    if not final_response or len(final_response.strip()) == 0:
        logger.warning("[MEM0_EXTRACTION] Skipped: No final_response found in state.")
        return {}

    with observability.trace_node("memory_extraction_node"):
        _enqueue_post_response_task(
            {
                "kind": "mem0_extract",
                "user_input": user_input,
                "final_response": final_response,
            }
        )
        return {}



# ============================================
# NODE: COMPLIANCE (RAG Search)
# ============================================

def compliance_node(state: KuroState) -> Dict[str, Any]:
    """
    Compliance Node: Searches ChromaDB for compliance/ISO references.
    Wraps the existing RAG functionality from memory_manager.py.
    """
    user_input = state.get("user_input", "")
    query_expansion_count = state.get("query_expansion_count", 0)
    session_id = state.get("_session_id", "unknown")
    trace_attrs = observability.create_session_context(session_id=session_id)
    trace_attrs = observability.add_client_label(trace_attrs, user_input)
    
    with observability.trace_node("compliance_node", trace_attrs) as span:
        # Search compliance knowledge base
        compliance_results = memory_manager.search_compliance_base(user_input, top_k=5)
        
        # If no results and we're in self-correction mode, try query expansion
        if not compliance_results and query_expansion_count > 0:
            # Simple query expansion: add common ISO terms
            expanded_query = f"{user_input} ISO standard control requirement"
            compliance_results = memory_manager.search_compliance_base(expanded_query, top_k=5)
            logger.info(f"[COMPLIANCE] Query expanded to: {expanded_query}")
        
        # Format compliance data for state
        formatted_data = []
        for result in compliance_results:
            formatted_data.append({
                "content": result.get("content", "")[:500],
                "iso_name": result.get("iso_name", "Unknown"),
                "clauses": result.get("clauses", ""),
                "relevance": result.get("relevance", 0)
            })
        
        logger.info(f"[COMPLIANCE] Found {len(formatted_data)} results for query")
        
        if span:
            span.set_attribute("compliance_node.results_count", len(formatted_data))
            span.set_attribute("compliance_node.query_expanded", query_expansion_count > 0)
        
        return {
            "compliance_data": formatted_data,
            "next_step": "response_node"  # After compliance, go to response
        }


# ============================================
# NODE: HABIT (SQLite Query)
# ============================================

def habit_node(state: KuroState) -> Dict[str, Any]:
    """
    Habit Node: Queries SQLite for habit data and calculates success rates.
    Wraps the existing daily_habits_db functionality.
    """
    user_input = state.get("user_input", "").lower()
    session_id = state.get("_session_id", "unknown")
    trace_attrs = observability.create_session_context(session_id=session_id)
    
    with observability.trace_node("habit_node", trace_attrs) as span:
        # Get all habits
        habits = core_data.get_all_habits()
        
        # Get today's stats
        stats = core_data.get_completion_stats()
        
        sqlite_snapshot = habit_service.fetch_sqlite_habit_snapshot(days=30)
        habit_service.log_snapshot_debug(sqlite_snapshot)

        # Check if user is asking for evaluation
        is_evaluation_request = any(kw in user_input for kw in ["evaluasi", "evaluation", "raport", "report", "laporan"])
        
        habit_data = {
            "habits": habits,
            "stats": stats,
            "is_evaluation_request": is_evaluation_request,
            "evaluation_text": "",
            "from_sqlite": True,
            "sqlite_snapshot_empty_activity": habit_service.snapshot_has_no_positive_activity(sqlite_snapshot),
        }
        
        # If evaluation requested, generate AI evaluation
        if is_evaluation_request and habits:
            try:
                from google import genai
                from google.genai import types
                
                client = genai.Client(api_key=settings.GEMINI_API_KEY)
                
                # Get monthly data for evaluation
                today = datetime.now()
                monthly_data = core_data.get_monthly_report_data(today.year, today.month)
                
                eval_user_prompt = habit_service.build_monthly_eval_user_prompt(monthly_data)
                
                response = client.models.generate_content(
                    model=PRIMARY_MODEL,
                    contents=eval_user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=habit_service.STRICT_HABIT_NARRATIVE_INSTRUCTION,
                        temperature=0.35,
                        max_output_tokens=2000
                    )
                )
                
                habit_data["evaluation_text"] = response.text if response.text else ""
                
                # Check if scolding is needed
                overall_score = float(monthly_data.get("overall_score", "100").replace("%", ""))
                habit_data["is_scolding_needed"] = overall_score < 90
                
            except Exception as e:
                logger.error(f"[HABIT] Evaluation generation failed: {e}")
                habit_data["evaluation_text"] = f"Maaf, gagal membuat evaluasi: {e}"
                habit_data["is_scolding_needed"] = False
        
        # Determine if scolding is needed based on user input
        if any(kw in user_input for kw in ["udah gym", "done tryhackme", "selesai belajar"]):
            habit_data["is_scolding_needed"] = False
        
        logger.info(f"[HABIT] Retrieved {len(habits)} habits, stats: {stats}")
        
        if span:
            span.set_attribute("habit_node.habits_count", len(habits))
            span.set_attribute("habit_node.evaluation_requested", is_evaluation_request)
        
        return {
            "habit_data": habit_data,
            "is_scolding_needed": habit_data.get("is_scolding_needed", False),
            "next_step": "response_node"
        }


# ============================================
# NODE: RESPONSE GENERATOR (Final Answer - No Guardrails)
# ============================================

def response_node(state: KuroState) -> Dict[str, Any]:
    """
    Response Generator Node: Synthesizes all state data into final response.
    V5.0: Guardrails validation removed. Direct LLM response is returned.
    """
    user_input = state.get("user_input", "")
    compliance_data = state.get("compliance_data", [])
    habit_data = state.get("habit_data", {})
    persona_mode = memory_manager.normalize_persona(
        state.get("persona_mode", memory_manager.get_active_persona())
    )
    image_paths = state.get("image_paths")
    is_scolding_needed = state.get("is_scolding_needed", False)
    mem0_memories = state.get("mem0_retrieved_memories", [])
    tool_result = state.get("tool_execution_result", {})
    session_id = state.get("_session_id", "unknown")
    
    # Observability tracing
    trace_attrs = observability.create_session_context(session_id=session_id)
    trace_attrs = observability.add_client_label(trace_attrs, user_input)
    
    with observability.trace_node("response_node", trace_attrs) as span:
        # Build memory injection
        recent_messages = memory_manager.get_short_term(persona_scope=persona_mode)
        memory = memory_manager.query_memory(
            user_input,
            recent_messages=recent_messages,
            persona_scope=persona_mode,
            include_compliance=not bool(compliance_data),
        )
        memory_injection = memory_manager.format_memory_with_temporal_grounding(memory)
        
        # Build system prompt
        system_prompt = get_system_instruction(persona_override=persona_mode)
        
        # Build user message with context injection
        message_parts = [user_input]
        
        # === MEM0 PERPETUAL MEMORY INJECTION ===
        if mem0_memories:
            mem0_context = perpetual_memory.perpetual_memory.format_memories_for_context(mem0_memories)
            if mem0_context:
                message_parts.append(f"\n\n[USER_CONTEXT - PERPETUAL MEMORY]\n{mem0_context}")
                logger.info(f"[MEM0] Injected {len(mem0_memories)} memories into context")
        
        # Add compliance context if available
        if compliance_data:
            compliance_context = "\n\n[COMPLIANCE REFERENCES]\n"
            for i, ref in enumerate(compliance_data, 1):
                compliance_context += f"{i}. [{ref['iso_name']}] Klausul: {ref['clauses']}\n{ref['content'][:300]}\n\n"
            message_parts.append(compliance_context)
        
        # Habit grounding: must run for habit_node path even when habits=[] (avoid Tier-1 hallucinations)
        if habit_data.get("from_sqlite"):
            snap = habit_service.fetch_sqlite_habit_snapshot(days=30)
            habit_service.log_snapshot_debug(snap, prefix="[RESPONSE]")
            habit_block = habit_service.format_habit_block_for_llm(
                snap,
                evaluation_text=habit_data.get("evaluation_text") or "",
            )
            message_parts.append("\n\n" + habit_block)
        
        # Add memory injection
        message_parts.append(memory_injection)
        
        # Add tool execution result if available
        if tool_result and tool_result.get("status"):
            if tool_result["status"] == "success":
                tool_context = f"\n\n[TOOL EXECUTION RESULT]\nTool: {tool_result.get('tool', 'unknown')}\nResult: {tool_result.get('result', '')}\n\nPlease inform the user about the successful tool execution in a professional manner."
                message_parts.append(tool_context)
            elif tool_result["status"] == "pending_approval":
                tool_context = (
                    f"\n\n[HITL APPROVAL REQUIRED]\n"
                    f"{tool_result.get('message', 'Approval needed for tool execution.')}\n\n"
                    "Ask user to reply exactly with `approve <nonce>` to proceed."
                )
                message_parts.append(tool_context)
            elif tool_result["status"] == "error":
                tool_context = f"\n\n[TOOL ERROR]\nError: {tool_result.get('message', 'Unknown error')}\n\nInform the user about the error professionally."
                message_parts.append(tool_context)
            elif tool_result["status"] == "no_tool":
                # No tool was needed, proceed normally
                pass
        
        # Build final message
        full_message = "\n".join(message_parts)
        
        # Generate response using direct google-genai SDK (more reliable)
        response_text = None  # Initialize to detect if generation fails
        try:
            from google import genai
            from google.genai import types
            
            genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
            
            response = genai_client.models.generate_content(
                model=PRIMARY_MODEL,
                contents=full_message,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    top_p=0.8,
                )
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

        # Canonical served response must match persisted response for integrity.
        response_text = sniper_pipeline.sniper_postprocess_output(user_input, response_text)

        # Store to memory (preserve existing memory flow)
        memory_manager.add_short_term("user", user_input, persona_scope=persona_mode)
        memory_manager.add_short_term("assistant", response_text, persona_scope=persona_mode)
        
        # FIX: DO NOT save to chat_history here - it's saved in the streaming/non-streaming
        # entry points to prevent duplicate database inserts (3-bubble bug).
        # chat_history.add_message("web", "user", user_input)
        # chat_history.add_message("web", "assistant", response_text)
        
        # Offload heavy writes out of request critical path.
        _enqueue_post_response_task(
            {
                "kind": "memory_write",
                "user_input": user_input,
                "final_response": response_text,
                "persona_scope": persona_mode,
            }
        )
        
        logger.info(f"[RESPONSE] Generated response ({len(response_text)} chars)")
        
        if span:
            span.set_attribute("response_node.response_length", len(response_text))
        
        return {
            "final_response": response_text,
        }


# ============================================
# NODE: TOOL EXECUTOR (The Hands)
# ============================================

def tool_node(state: KuroState) -> Dict[str, Any]:
    """
    Tool Node: Executes system tools based on user intent.
    Uses LLM to parse tool calls from the user message.
    
    Tools available:
    - generate_excel_report: Create Excel files from JSON data
    - manage_files: List, read, write, delete files in /home/kuro/exports/
    - generate_report_template: Generate audit/compliance report templates
    - advanced_execution_tool: Delegate complex system automation to OpenClaw
    """
    from kuro_backend.tools.system_tools import (
        generate_excel_report,
        manage_files,
        generate_report_template,
        TOOL_DESCRIPTIONS
    )
    
    user_input = state.get("user_input", "")
    session_id = state.get("_session_id", "unknown")
    trace_attrs = observability.create_session_context(session_id=session_id)
    
    with observability.trace_node("tool_node", trace_attrs) as span:
        try:
            # Use LLM to determine which tool to call and with what arguments
            from google import genai
            from google.genai import types
            
            genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
            
            tool_prompt = f"""You are a tool router. Analyze the user's request and determine which tool to call.

AVAILABLE TOOLS:
1. generate_excel_report(data, filename, sheet_name) - Create Excel from JSON data
2. manage_files(action, filename, content) - Manage files (list, read, write, delete, info)
3. generate_report_template(template_type, filename, data, format) - Generate report templates
4. advanced_execution_tool(task_description, params, skill_name) - Delegate complex execution tasks to OpenClaw

USER REQUEST: {user_input}

Respond with ONLY a JSON object in this format:
{{"tool": "tool_name", "args": {{"arg1": "value1", ...}}}}

If no tool is appropriate, respond with: {{"tool": null, "reason": "explanation"}}

POLICY:
- Use advanced_execution_tool for complex execution tasks.
- If task is read-only (search/analyze/mapping), include args.execution_mode=\"readonly\".
- If task can modify/delete/format/reboot system state, include args.execution_mode=\"mutating\".

Examples:
- "Buatkan excel audit" -> {{"tool": "manage_files", "args": {{"action": "list"}}}}
- "List file di exports" -> {{"tool": "manage_files", "args": {{"action": "list"}}}}
- "Buat laporan audit" -> {{"tool": "generate_report_template", "args": {{"template_type": "audit_findings", "filename": "audit_report.md"}}}}
- "Kuro tolong bersihkan log lama di Proxmox pake OpenClaw" -> {{"tool": "advanced_execution_tool", "args": {{"task_description": "bersihkan log lama di Proxmox", "skill_name": "general_execution"}}}}
- "Cari paper terbaru digital forensics on AI" -> {{"tool": "advanced_execution_tool", "args": {{"task_description": "cari paper terbaru digital forensics on AI", "skill_name": "general_execution", "execution_mode": "readonly"}}}}

TOOL CALL:"""
            
            response = genai_client.models.generate_content(
                model=PRIMARY_MODEL,
                contents=tool_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=500,
                )
            )
            
            tool_call_text = response.text.strip()
            logger.info(f"[TOOL_NODE] LLM tool call: {tool_call_text}")
            
            # Parse tool call
            try:
                # Extract JSON from response
                json_match = re.search(r'\{.*\}', tool_call_text, re.DOTALL)
                if json_match:
                    tool_call = json.loads(json_match.group())
                else:
                    tool_call = {"tool": None, "reason": "Could not parse tool call"}
            except json.JSONDecodeError:
                tool_call = {"tool": None, "reason": f"Invalid JSON: {tool_call_text}"}
            
            tool_name = tool_call.get("tool")
            
            if not tool_name:
                # No tool needed, pass through to response node
                if span:
                    span.set_attribute("tool_node.tool_used", "none")
                return {
                    "tool_execution_result": {"status": "no_tool", "message": tool_call.get("reason", "")},
                    "next_step": "response_node"
                }
            
            # Check for HITL interrupt (file write/delete operations)
            args = tool_call.get("args", {})
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


def _execute_tool(tool_name: str, args: Dict) -> Dict[str, Any]:
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
    START -> supervisor_node -> memory_retrieval -> [compliance_node | habit_node | tool_node | response_node] -> response_node -> memory_extraction -> END
    
    Self-Correction Loop:
    compliance_node -> (if empty) -> supervisor_node (with expanded query)
    """
    
    # Initialize checkpointer for persistence
    checkpointer = MemorySaver()
    
    # Create state graph
    graph_builder = StateGraph(KuroState)
    
    # Add nodes
    graph_builder.add_node("supervisor_node", supervisor_node)
    graph_builder.add_node("memory_retrieval_node", memory_retrieval_node)
    graph_builder.add_node("compliance_node", compliance_node)
    graph_builder.add_node("habit_node", habit_node)
    graph_builder.add_node("tool_node", tool_node)
    graph_builder.add_node("response_node", response_node)
    graph_builder.add_node("memory_extraction_node", memory_extraction_node)
    
    # Set entry point using START constant (LangGraph v0.2+ compatible)
    graph_builder.add_edge(START, "supervisor_node")
    
    # After supervisor, run memory retrieval in parallel
    graph_builder.add_edge("supervisor_node", "memory_retrieval_node")
    
    # Add conditional edges from memory retrieval
    graph_builder.add_conditional_edges(
        "memory_retrieval_node",
        route_after_supervisor,
        {
            "compliance_node": "compliance_node",
            "habit_node": "habit_node",
            "tool_node": "tool_node",
            "response_node": "response_node",
            "__end__": END,
        }
    )
    
    # Add edges from worker nodes to response
    graph_builder.add_edge("compliance_node", "response_node")
    graph_builder.add_edge("habit_node", "response_node")
    graph_builder.add_edge("tool_node", "response_node")
    
    # V5.0: Direct edge from response_node to memory_extraction_node (no re-ask loop)
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
# ASYNC STREAMING ENTRY POINT (Project Quicksilver V5.1)
# ============================================

async def process_chat_with_graph_stream(
    message: str,
    image_paths: list = None,
    persona_override: str = None,
    stream_metrics: Optional[Dict[str, Any]] = None,
    approval_scope: str = "default",
    trace_id: str = "",
) -> AsyncGenerator[str, None]:
    """
    V5.3 STREAMING: Graph runs in asyncio.to_thread (sync stream) so the event loop can serve SSE.
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

        guard_in_started = time.perf_counter()
        blocked = await sniper_pipeline.sniper_validate_and_maybe_block_input_async(message)
        if stream_metrics is not None:
            stream_metrics["guardrail_input_ms"] = round((time.perf_counter() - guard_in_started) * 1000, 2)
        if blocked:
            logger.debug("[SNIPER] Input blocked before graph invoke (stream)")
            yield blocked
            return

        persona_mode = memory_manager.normalize_persona(
            persona_override or memory_manager.get_active_persona()
        )
        can_use_true_stream = (
            _TRUE_TOKEN_STREAMING_ENABLED
            and not image_paths
            and sniper_pipeline.is_low_risk_stream_candidate(message)
        )
        if stream_metrics is not None:
            stream_metrics["stream_mode"] = "true_token_fastpath" if can_use_true_stream else "graph_collect_chunked"

        if can_use_true_stream:
            fastpath_started = time.perf_counter()
            recent_messages = memory_manager.get_short_term(persona_scope=persona_mode)
            memory_started = time.perf_counter()
            memory = memory_manager.query_memory(
                message,
                recent_messages=recent_messages,
                persona_scope=persona_mode,
                include_compliance=True,
            )
            if stream_metrics is not None:
                stream_metrics["memory_query_ms"] = round((time.perf_counter() - memory_started) * 1000, 2)
            memory_injection = memory_manager.format_memory_with_temporal_grounding(memory)
            full_message = f"{message}{memory_injection}"
            system_prompt = get_system_instruction(persona_override=persona_mode)

            emitted = 0
            response_acc: List[str] = []
            stream_llm_started = time.perf_counter()
            async for live_chunk in _stream_direct_llm_chunks(system_prompt, full_message):
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
            if stream_metrics is not None:
                stream_metrics["response_chars"] = float(len(response_text))
                stream_metrics["stream_total_ms"] = round((time.perf_counter() - fastpath_started) * 1000, 2)
            return
        
        initial_state = {
            "messages": [{"role": "user", "content": message}],
            "next_step": "",
            "compliance_data": [],
            "habit_data": {},
            "is_scolding_needed": False,
            "user_input": message,
            "final_response": "",
            "query_expansion_count": 0,
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
    image_paths: list = None,
    persona_override: str = None,
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

        blocked = sniper_pipeline.sniper_validate_and_maybe_block_input(message)
        if blocked:
            logger.info("[SNIPER] Input blocked before graph invoke")
            return blocked

        # Get current persona
        persona_mode = memory_manager.normalize_persona(
            persona_override or memory_manager.get_active_persona()
        )

        # Initialize state with session ID for observability
        initial_state = {
            "messages": [{"role": "user", "content": message}],
            "next_step": "",
            "compliance_data": [],
            "habit_data": {},
            "is_scolding_needed": False,
            "user_input": message,
            "final_response": "",
            "query_expansion_count": 0,
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
        return response
        
    except Exception as e:
        logger.exception(f"[LANGGRAPH] Graph invocation failed: {e}")
        return "Maaf, Pantronux. Kuro mengalami kendala sistem. Silakan coba lagi."


# ============================================
# GRAPH VISUALIZATION (Debug)
# ============================================

def save_graph_visualization(path: str = "kuro_graph.png"):
    """Save graph visualization as PNG."""
    try:
        from IPython.display import Image, display
        # This requires graphviz installed
        # graph_image = kuro_graph.get_graph().draw_mermaid_png()
        logger.info(f"[LANGGRAPH] Graph visualization saved to {path}")
    except Exception as e:
        logger.warning(f"[LANGGRAPH] Could not save graph visualization: {e}")
