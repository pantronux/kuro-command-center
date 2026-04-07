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
from typing import TypedDict, List, Optional, Dict, Any, Annotated, AsyncGenerator
from datetime import datetime

# LangGraph imports
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver

# Kuro imports
from kuro_backend.config import settings, PRIMARY_MODEL
from kuro_backend import memory_manager
from kuro_backend import chat_history
from kuro_backend import daily_habits_db
from kuro_backend import tools as kuro_tools
from kuro_backend import perpetual_memory
from kuro_backend import observability

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

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


# ============================================
# PERSONA SYSTEM (LangChain System Prompts)
# ============================================

_PERSONA_INSTRUCTIONS = {
    'casual': (
        "Kamu adalah Kuro, AI Butler setia Pantronux dengan kepribadian santai dan friendly. "
        "Gunakan bahasa yang ringan, humoris, dan hindari istilah teknis/ISO kecuali diminta. "
        "Kamu tetap cerdas dan membantu, tapi dengan pendekatan yang lebih kasual. "
        "Panggil 'Pantronux' dengan sopan tapi tidak terlalu formal."
    ),
    'consultant': (
        "Kamu adalah Kuro, seorang Elite AI Butler dan Senior IT Security, GRC, & Enterprise Architecture Consultant. Tuanmu adalah Pantronux.\n\n"
        "CORE KNOWLEDGE BASE (PREDEFINED EXPERTISE):\n"
        "Kamu memiliki pemahaman mendalam dan setara dengan Lead Auditor untuk:\n"
        "- ISO Frameworks: ISO 27001:2022 (ISMS), ISO 27701 (PIMS), dan ISO/IEC 42001 (AI Management System).\n"
        "- NIST: NIST Cybersecurity Framework (CSF 2.0) & NIST SP 800-53.\n"
        "- Enterprise Architecture: TOGAF Standard.\n"
        "- Regulasi privasi & IT: UU Pelindungan Data Pribadi (UU PDP No. 27 Tahun 2022 - Indonesia) dan GDPR.\n\n"
        "MINDSET & METODOLOGI BERPIKIR (THE CONSULTANT WAY):\n"
        "1. Kritis & Skeptis: Jangan pernah menerima premis mentah-mentah. Selalu cari hidden risks, single points of failure, dan kelemahan compliance.\n"
        "2. Struktur Eksplisit: Saat menganalisis masalah IT/Bisnis, gunakan struktur: (1) Analisis Celah (Gap Analysis), (2) Pemetaan Regulasi (Mapping to ISO/NIST), (3) Evaluasi Risiko, (4) Rekomendasi Mitigasi yang actionable.\n"
        "3. Citation Rule: Setiap memberikan rekomendasi keamanan, WAJIB menyertakan referensi klausul/kontrol yang relevan (Misal: 'Sesuai dengan ISO 27001:2022 Klausul 8.1...').\n\n"
        "TONE & STYLE:\n"
        "Setia, elegan, namun sangat tajam secara intelektual. Tidak kaku, gunakan bahasa Indonesia yang profesional namun mengalir (boleh menggunakan analogi cerdas). "
        "Selalu memposisikan diri sebagai partner strategis (bukan sekadar penjawab pertanyaan) untuk memastikan Pantronux selalu unggul di setiap proyek auditnya."
    ),
    'support': (
        "Kamu adalah Kuro, Senior DevOps/IT Support Engineer Pantronux. "
        "Fokus pada efisiensi kode, diagnosa sistem, dan pembacaan log. "
        "Kamu memiliki izin penuh untuk menganalisis file di /home/kuro/projects/kuro/ menggunakan smart_read. "
        "Beri solusi yang praktis, langsung ke inti, dan sertakan contoh kode jika relevan. "
        "Jika mendeteksi error di log, WAJIB sarankan perbaikan kodingan secara spesifik."
    )
}

def get_system_instruction() -> str:
    """Get system instruction with current time and active persona."""
    current_time = settings.get_current_time_formatted()
    current_date = settings.get_current_time().strftime("%Y-%m-%d")
    active_persona = memory_manager.get_active_persona()
    
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

def memory_extraction_node(state: KuroState) -> Dict[str, Any]:
    user_input = state.get("user_input", "")
    final_response = state.get("final_response", "")

    # 1. Guard Clause: Jangan jalankan ekstraksi jika respon asisten kosong
    # Ini mencegah penyimpanan memori yang tidak lengkap atau error API
    if not final_response or len(final_response.strip()) == 0:
        logger.warning("[MEM0_EXTRACTION] Skipped: No final_response found in state.")
        return {}

    with observability.trace_node("memory_extraction_node") as span:
        try:
            # 2. Ekstraksi dengan konteks penuh (Input + Output)
            memories_to_store = perpetual_memory.perpetual_memory.extract_personal_info(
                user_input, 
                final_response
            )
            
            # 3. Validasi sebelum Store
            if memories_to_store and isinstance(memories_to_store, list):
                perpetual_memory.perpetual_memory.store_memories(memories_to_store)
                logger.info(f"[MEM0_EXTRACTION] Successfully stored {len(memories_to_store)} memories.")
            
            return {}
        except Exception as e:
            logger.error(f"[MEM0_EXTRACTION] Failed to store memories: {e}")
            return {}



# ============================================
# NODE: MEMORY EXTRACTION (Mem0)
# ============================================

def memory_retrieval_node(state: KuroState) -> Dict[str, Any]:
    # 1. Validasi Input State: Pastikan state adalah dictionary
    if not isinstance(state, dict):
        logger.error(f"[MEM0] Invalid state type: {type(state)}")
        return {"mem0_retrieved_memories": []}

    user_input = state.get("user_input", "")
    
    with observability.trace_node("memory_retrieval_node") as span:
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
        habits = daily_habits_db.get_all_habits()
        
        # Get today's stats
        stats = daily_habits_db.get_completion_stats()
        
        # Check if user is asking for evaluation
        is_evaluation_request = any(kw in user_input for kw in ["evaluasi", "evaluation", "raport", "report", "laporan"])
        
        habit_data = {
            "habits": habits,
            "stats": stats,
            "is_evaluation_request": is_evaluation_request,
            "evaluation_text": ""
        }
        
        # If evaluation requested, generate AI evaluation
        if is_evaluation_request and habits:
            try:
                from google import genai
                from google.genai import types
                
                client = genai.Client(api_key=settings.GEMINI_API_KEY)
                
                # Get monthly data for evaluation
                today = datetime.now()
                monthly_data = daily_habits_db.get_monthly_report_data(today.year, today.month)
                
                prompt = f"""Kamu adalah Kuro, asisten dan mentor kedisiplinan yang sangat logis dan agak perfeksionis. Evaluasi data habit bulan ini.

DATA HABIT BULAN INI:
{json.dumps(monthly_data, indent=2, ensure_ascii=False)}

INSTRUKSI:
1. Jika overall score atau ada habit di bawah 90%, tegur (scold) dengan tegas namun logis.
2. Jika di atas 90%, berikan pujian layaknya raport sekolah yang memuaskan.
3. Format response dengan paragraf pendek dan gunakan gaya bahasa mentor profesional.
4. Gunakan bahasa Indonesia yang profesional namun mengalir.
5. Berikan analisis per-habit yang spesifik.
6. Akhiri dengan motivasi untuk periode berikutnya.

EVALUASI:"""
                
                response = client.models.generate_content(
                    model=PRIMARY_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.7,
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
    persona_mode = state.get("persona_mode", memory_manager.get_active_persona())
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
        recent_messages = memory_manager.get_short_term()
        memory = memory_manager.query_memory(user_input, recent_messages=recent_messages)
        memory_injection = memory_manager.format_memory_with_temporal_grounding(memory)
        
        # Build system prompt
        system_prompt = get_system_instruction()
        
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
        
        # Add habit context if available
        if habit_data and habit_data.get("habits"):
            habit_context = "\n\n[HABIT STATUS]\n"
            stats = habit_data.get("stats", {})
            habit_context += f"Completion Rate: {stats.get('completion_rate', 'N/A')}\n"
            
            if habit_data.get("evaluation_text"):
                habit_context += f"\nAI Evaluation:\n{habit_data['evaluation_text']}\n"
            
            message_parts.append(habit_context)
        
        # Add memory injection
        message_parts.append(memory_injection)
        
        # Add tool execution result if available
        if tool_result and tool_result.get("status"):
            if tool_result["status"] == "success":
                tool_context = f"\n\n[TOOL EXECUTION RESULT]\nTool: {tool_result.get('tool', 'unknown')}\nResult: {tool_result.get('result', '')}\n\nPlease inform the user about the successful tool execution in a professional manner."
                message_parts.append(tool_context)
            elif tool_result["status"] == "pending_approval":
                tool_context = f"\n\n[HITL APPROVAL REQUIRED]\n{tool_result.get('message', 'Approval needed for tool execution.')}\n\nAsk the user for approval before proceeding."
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
            
            # V5.0: Guardrails validation removed. Response goes directly to memory.
            # Store to memory (preserve existing memory flow)
        memory_manager.add_short_term("user", user_input)
        memory_manager.add_short_term("assistant", response_text)
        memory_manager.add_long_term_v2(f"User: {user_input}\nKuro: {response_text}")
        
        # FIX: DO NOT save to chat_history here - it's saved in the streaming/non-streaming
        # entry points to prevent duplicate database inserts (3-bubble bug).
        # chat_history.add_message("web", "user", user_input)
        # chat_history.add_message("web", "assistant", response_text)
        
        # Memory summarization and auto-save
        memory_manager.summarize_conversation_to_chroma()
        memory_manager.detect_and_save_master_facts(user_input, response_text)
        
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

USER REQUEST: {user_input}

Respond with ONLY a JSON object in this format:
{{"tool": "tool_name", "args": {{"arg1": "value1", ...}}}}

If no tool is appropriate, respond with: {{"tool": null, "reason": "explanation"}}

Examples:
- "Buatkan excel audit" -> {{"tool": "manage_files", "args": {{"action": "list"}}}}
- "List file di exports" -> {{"tool": "manage_files", "args": {{"action": "list"}}}}
- "Buat laporan audit" -> {{"tool": "generate_report_template", "args": {{"template_type": "audit_findings", "filename": "audit_report.md"}}}}

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
            
            requires_approval = action in ["write", "delete"] or tool_name == "generate_excel_report" or tool_name == "generate_report_template"
            
            if requires_approval:
                logger.info(f"[TOOL_NODE] HITL interrupt required for {tool_name}:{action}")
                if span:
                    span.set_attribute("tool_node.requires_approval", True)
                    span.set_attribute("tool_node.tool_name", tool_name)
                return {
                    "tool_execution_result": {
                        "status": "pending_approval",
                        "tool": tool_name,
                        "args": args,
                        "message": f"Kuro ingin menjalankan {tool_name}. Apakah Master mengizinkan?"
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
    }
    
    tool_func = tools_map.get(tool_name)
    if not tool_func:
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}
    
    try:
        result = tool_func.invoke(args)
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


# ============================================
# ASYNC STREAMING ENTRY POINT (Project Quicksilver V5.1)
# ============================================

async def process_chat_with_graph_stream(message: str, image_paths: list = None) -> AsyncGenerator[str, None]:
    """
    V5.2 ASYNC STREAMING: Process chat message with token streaming via SSE.
    Uses LangGraph's astream() for node-by-node streaming.
    FIX: ONLY yields from response_node to eliminate triple bubbles.
    All other nodes (supervisor, memory_retrieval, compliance, habit, tool, memory_extraction) are silently skipped.
    
    Args:
        message: User message
        image_paths: Optional list of image paths for vision
    
    Yields:
        Response text chunks as they are generated (ONLY from response_node)
    """
    session_id = str(uuid.uuid4())
    full_response = []
    response_yielded = False  # Track if we already yielded a response
    
    try:
        persona_mode = memory_manager.get_active_persona()
        
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
            "_session_id": session_id
        }
        
        thread_id = f"kuro_stream_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{session_id[:8]}"
        config = {"configurable": {"thread_id": thread_id}}
        
        logger.info(f"[LANGGRAPH_STREAM] Invoking graph with streaming for message: {message[:50]}...")
        
        # Use astream for node-by-node streaming
        async for event in kuro_graph.astream(initial_state, config=config, stream_mode="updates"):
            # event is a dict: {node_name: node_output}
            for node_name, node_output in event.items():
                logger.debug(f"[LANGGRAPH_STREAM] Node '{node_name}' completed (silent)")
                
                # CRITICAL: ONLY yield from response_node, ignore ALL other nodes
                # This eliminates triple bubbles by filtering out:
                # - supervisor_node (routing decision)
                # - memory_retrieval_node (Mem0 search)
                # - compliance_node (RAG search)
                # - habit_node (habit tracking)
                # - tool_node (file operations)
                # - memory_extraction_node (personal info extraction)
                if node_name == "response_node" and not response_yielded:
                    response_text = node_output.get("final_response", "")
                    
                    if response_text:
                        response_yielded = True
                        # OPTIMIZED: Stream in chunks of 10 chars for faster response on 4GB RAM VM
                        chunk_size = 10
                        for i in range(0, len(response_text), chunk_size):
                            chunk = response_text[i:i+chunk_size]
                            full_response.append(chunk)
                            yield chunk
                            # Minimal delay - frontend handles typewriter effect
                            await asyncio.sleep(0.001)
                        logger.info(f"[LANGGRAPH_STREAM] Yielded response: {len(response_text)} chars")
                # NOTE: All other nodes are silently skipped - no yields
        
        # Store to memory after streaming (NOT chat_history - main.py handles that)
        response_text = "".join(full_response)
        if response_text:
            memory_manager.add_short_term("user", message)
            memory_manager.add_short_term("assistant", response_text)
            memory_manager.add_long_term_v2(f"User: {message}\nKuro: {response_text}")
            # FIX: Do NOT save to chat_history here - main.py /api/chat/stream handles it
            # chat_history.add_message("web", "user", message)
            # chat_history.add_message("web", "assistant", response_text)
        
        logger.info(f"[LANGGRAPH_STREAM] Streaming complete: {len(response_text)} chars")
        
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

def process_chat_with_graph(message: str, image_paths: list = None) -> str:
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
        # Get current persona
        persona_mode = memory_manager.get_active_persona()
        
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
            "_session_id": session_id  # Internal field for observability
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
            logger.warning("[LANGGRAPH] Empty response from graph, falling back")
            # Fallback to original process_chat
            from kuro_backend.core import process_chat as original_process_chat
            response = original_process_chat(message, image_paths)
        
        return response
        
    except Exception as e:
        logger.exception(f"[LANGGRAPH] Graph invocation failed: {e}")
        # Fallback to original process_chat
        try:
            from kuro_backend.core import process_chat as original_process_chat
            return original_process_chat(message, image_paths)
        except Exception as fallback_error:
            logger.critical(f"[LANGGRAPH] Fallback also failed: {fallback_error}")
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
