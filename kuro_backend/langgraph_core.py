"""
Kuro AI V4.8 Official - LangGraph Core with Observability [2026-04-06]
================================================================================
AI Core with LangGraph Stateful Architecture for Agentik Long-Term Reasoning
SDK: google-genai v3 Protocol with LangGraph State Machine
V4.8: LangGraph Engine + Stateful Memory + Self-Correction Loops + Arize Phoenix Observability
"""
import logging
import os
import json
import re
import uuid
import time
from typing import TypedDict, List, Optional, Dict, Any, Annotated
from datetime import datetime

# LangGraph imports
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

# LangChain imports
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langchain_core.tools import tool

# Kuro imports
from kuro_backend.config import settings, PRIMARY_MODEL
from kuro_backend import memory_manager
from kuro_backend import chat_history
from kuro_backend import daily_habits_db
from kuro_backend import tools as kuro_tools
from kuro_backend import perpetual_memory
from kuro_backend import observability

logger = logging.getLogger(__name__)

# ============================================
# AGENT STATE DEFINITION (The Memory)
# ============================================

class KuroState(TypedDict):
    """
    Kuro Agent State - persists across graph nodes.
    
    Fields:
    - messages: Conversation history (LangChain format)
    - next_step: Next node to route to (supervisor decision)
    - compliance_data: Results from compliance RAG search
    - habit_data: Results from habit database query
    - is_scolding_needed: Flag for habit evaluation trigger
    - user_input: Original user message
    - final_response: Generated response to return
    - query_expansion_count: Track self-correction iterations
    - persona_mode: Current active persona
    - guardrail_reask_count: Track guardrail re-ask attempts
    - guardrail_feedback: Feedback from guardrails for re-generation
    - mem0_retrieved_memories: Memories retrieved from Mem0 for context
    - tool_execution_result: Result from tool execution (ToolNode output)
    - requires_approval: Flag for HITL interrupt (file operations need approval)
    """
    messages: Annotated[List[BaseMessage], lambda x, y: x + y]
    next_step: str
    compliance_data: List[Dict]
    habit_data: Dict
    is_scolding_needed: bool
    user_input: str
    final_response: str
    query_expansion_count: int
    persona_mode: str
    image_paths: Optional[List[str]]
    guardrail_reask_count: int
    guardrail_feedback: str
    mem0_retrieved_memories: List[Dict]
    tool_execution_result: Optional[Dict]
    requires_approval: bool


# ============================================
# LLM INITIALIZATION (LangChain Wrapper)
# ============================================

def create_llm() -> ChatGoogleGenerativeAI:
    """Create LangChain-wrapped Gemini LLM."""
    return ChatGoogleGenerativeAI(
        model=PRIMARY_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.2,
        top_p=0.8,
        max_output_tokens=4096,
    )

# Global LLM instance
llm = create_llm()

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

def memory_retrieval_node(state: KuroState) -> Dict[str, Any]:
    """
    Memory Retrieval Node: Searches Mem0 for relevant personal memories.
    Runs in parallel with supervisor to enrich context.
    """
    user_input = state.get("user_input", "")
    session_id = state.get("_session_id", "unknown")
    trace_attrs = observability.create_session_context(session_id=session_id)
    
    with observability.trace_node("memory_retrieval_node", trace_attrs) as span:
        # Retrieve relevant memories from Mem0
        memories = perpetual_memory.perpetual_memory.retrieve_memories(user_input, limit=5)
        
        logger.info(f"[MEM0_RETRIEVAL] Retrieved {len(memories)} memories for query: {user_input[:50]}...")
        
        if span:
            span.set_attribute("memory_retrieval_node.memories_count", len(memories))
        
        return {
            "mem0_retrieved_memories": memories
        }


# ============================================
# NODE: MEMORY EXTRACTION (Mem0)
# ============================================

def memory_extraction_node(state: KuroState) -> Dict[str, Any]:
    """
    Memory Extraction Node: Analyzes conversation for personal info to store.
    Runs after response generation to capture new memories.
    """
    user_input = state.get("user_input", "")
    final_response = state.get("final_response", "")
    session_id = state.get("_session_id", "unknown")
    trace_attrs = observability.create_session_context(session_id=session_id)
    
    with observability.trace_node("memory_extraction_node", trace_attrs) as span:
        # Extract personal information from conversation
        memories_to_store = perpetual_memory.perpetual_memory.extract_personal_info(user_input, final_response)
        
        # Store extracted memories
        if memories_to_store:
            perpetual_memory.perpetual_memory.store_memories(memories_to_store)
            logger.info(f"[MEM0_EXTRACTION] Stored {len(memories_to_store)} new memories")
        
        if span:
            span.set_attribute("memory_extraction_node.memories_stored", len(memories_to_store))
        
        # No state change needed - memories are stored externally
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
# NODE: RESPONSE GENERATOR (Final Answer with Guardrails)
# ============================================

def response_node(state: KuroState) -> Dict[str, Any]:
    """
    Response Generator Node: Synthesizes all state data into final response.
    Includes Guardrails AI validation with re-ask loop and Mem0 context injection.
    """
    user_input = state.get("user_input", "")
    compliance_data = state.get("compliance_data", [])
    habit_data = state.get("habit_data", {})
    persona_mode = state.get("persona_mode", memory_manager.get_active_persona())
    image_paths = state.get("image_paths")
    is_scolding_needed = state.get("is_scolding_needed", False)
    guardrail_reask_count = state.get("guardrail_reask_count", 0)
    guardrail_feedback = state.get("guardrail_feedback", "")
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
        
        # Add guardrail feedback if re-asking
        if guardrail_feedback:
            message_parts.append(f"\n\n[GUARDRAIL FEEDBACK]\n{guardrail_feedback}")
        
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
            
            response_text = response.text if response.text else "Maaf, Pantronux. Kuro tidak dapat menghasilkan respons yang valid."
            
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
            logger.error(f"[RESPONSE] LLM generation failed: {e}")
            response_text = f"Maaf, Pantronux. Terjadi kesalahan saat menghasilkan respons: {e}"
        
        # === GUARDRAILS VALIDATION ===
        from kuro_backend.guardrails import GuardrailsOrchestrator
        
        orchestrator = GuardrailsOrchestrator()
        validation_result = orchestrator.validate_response(
            response_text=response_text,
            user_query=user_input,
            compliance_data=compliance_data,
            is_scolding=is_scolding_needed,
            habit_data=habit_data
        )
        
        # Log guardrails validation to Phoenix
        observability.log_guardrails_validation(
            guardrail_type="compliance_privacy_tone",
            is_valid=validation_result.is_valid,
            original_response=response_text if not validation_result.is_valid else None,
            corrected_response=validation_result.corrected_text if validation_result.corrected_text else None,
            failures=validation_result.failures,
            reask_count=guardrail_reask_count,
            session_id=session_id
        )
        
        # Check if re-ask is needed
        if not validation_result.is_valid and guardrail_reask_count < 2:
            # Generate re-ask prompt
            reask_prompt = orchestrator.generate_reask_prompt(
                original_query=user_input,
                original_response=response_text,
                failures=validation_result.failures
            )
            
            logger.info(f"[GUARDRAILS] Re-ask triggered (attempt {guardrail_reask_count + 1}/2)")
            
            if span:
                span.set_attribute("response_node.guardrails_reask", True)
                span.set_attribute("response_node.reask_count", guardrail_reask_count + 1)
            
            return {
                "final_response": "",
                "guardrail_reask_count": guardrail_reask_count + 1,
                "guardrail_feedback": reask_prompt,
                "next_step": "response_node"  # Loop back to response_node
            }
        
        # Validation passed or max re-asks reached
        if not validation_result.is_valid:
            logger.warning(f"[GUARDRAILS] Max re-asks reached. Using fallback response.")
            response_text = f"[Guardrails Warning] Respons asli gagal validasi ({validation_result.failure_summary}). Silakan periksa kembali informasi."
        
        # Store to memory (preserve existing memory flow)
        memory_manager.add_short_term("user", user_input)
        memory_manager.add_short_term("assistant", response_text)
        memory_manager.add_long_term_v2(f"User: {user_input}\nKuro: {response_text}")
        
        # Store to chat history
        chat_history.add_message("web", "user", user_input)
        chat_history.add_message("web", "assistant", response_text)
        
        # Memory summarization and auto-save
        memory_manager.summarize_conversation_to_chroma()
        memory_manager.detect_and_save_master_facts(user_input, response_text)
        
        logger.info(f"[RESPONSE] Generated response ({len(response_text)} chars) | Guardrails: {'PASSED' if validation_result.is_valid else 'FAILED'}")
        
        if span:
            span.set_attribute("response_node.response_length", len(response_text))
            span.set_attribute("response_node.guardrails_passed", validation_result.is_valid)
        
        return {
            "final_response": response_text,
            "guardrail_reask_count": 0,  # Reset for next request
            "guardrail_feedback": ""
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
    
    # Set entry point
    graph_builder.set_entry_point("supervisor_node")
    
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
    
    # Response node has conditional edge: either loop back for re-ask or go to memory extraction
    def route_after_response(state: KuroState) -> str:
        """Route based on guardrail validation result."""
        reask_count = state.get("guardrail_reask_count", 0)
        feedback = state.get("guardrail_feedback", "")
        
        # If there's feedback and we haven't exceeded max re-asks, loop back
        if feedback and reask_count < 2:
            return "response_node"  # Loop back for re-generation
        return "memory_extraction_node"  # Go to memory extraction
    
    graph_builder.add_conditional_edges(
        "response_node",
        route_after_response,
        {
            "response_node": "response_node",
            "memory_extraction_node": "memory_extraction_node",
        }
    )
    
    # After memory extraction, go to END
    graph_builder.add_edge("memory_extraction_node", END)
    
    # Compile with checkpointer
    graph = graph_builder.compile(checkpointer=checkpointer)
    
    logger.info("[LANGGRAPH] Kuro graph compiled successfully with tool_node")
    return graph


# Global graph instance
kuro_graph = build_kuro_graph()


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
            "messages": [HumanMessage(content=message)],
            "next_step": "",
            "compliance_data": [],
            "habit_data": {},
            "is_scolding_needed": False,
            "user_input": message,
            "final_response": "",
            "query_expansion_count": 0,
            "persona_mode": persona_mode,
            "image_paths": image_paths,
            "guardrail_reask_count": 0,
            "guardrail_feedback": "",
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
