"""
Kuro AI V6.0 Sovereign - Core [2026-04-17]
================================================================================
AI Core with Contextual RAG Memory Injection and Dynamic Persona System
SDK: google-genai v3 Protocol (client.models.generate_content)
V5.5: Gemini 3 Flash Engine + Contextual Retrieval + Query Expansion

NOTE: This module is the legacy non-LangGraph path. Production traffic runs
through `kuro_backend.langgraph_core`. Kept for CLI smoke tests and
backward-compatible imports.

--- Header Doc ---
Purpose: Legacy single-shot Gemini chat path + generation-config factory (non-LangGraph).
Caller: CLI smoke tests, fallback orchestration in core_service when LangGraph is disabled.
Dependencies: google-genai, kuro_backend.chat_history, memory_manager, tools.base_tools, personas, config.
Main Functions: process_chat(), _get_generation_config(), _assemble_contents().
Side Effects: Gemini API calls, chat-history SQLite writes, token-usage metrics via observability.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Optional

from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError

from kuro_backend import chat_history, memory_manager, tools
from kuro_backend.config import PRIMARY_MODEL, settings
from kuro_backend.personas import (
    PERSONA_INSTRUCTIONS as _PERSONA_INSTRUCTIONS,  # re-export for backward compat
    build_system_instruction,
)

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

# Initialize the Generative AI client (SDK v3) - single instance for memory efficiency
client = genai.Client(api_key=settings.GEMINI_API_KEY)


def _get_system_instruction_with_time(persona_override: Optional[str] = None) -> str:
    """Get system instruction with current time injected and active persona."""
    current_time = settings.get_current_time_formatted()
    current_date = settings.get_current_time().strftime("%Y-%m-%d")
    active_persona = memory_manager.normalize_persona(
        persona_override or memory_manager.get_active_persona()
    )

    return build_system_instruction(
        active_persona,
        current_time=current_time,
        current_date=current_date,
        kuro_version_label="V5.5 Official - Contextual RAG",
        variant="core",
    )

# --- Reusable Generation Config (SDK v3 Protocol) ---
# Note: system_instruction is dynamic - rebuilt per request with current time
def _get_generation_config(persona_override: Optional[str] = None) -> types.GenerateContentConfig:
    """Build generation config with current system instruction + per-persona sampling."""
    from kuro_backend.personas import get_sampling_profile
    profile = get_sampling_profile(persona_override)
    return types.GenerateContentConfig(
        system_instruction=_get_system_instruction_with_time(persona_override=persona_override),
        temperature=profile.temperature,
        top_p=profile.top_p,
        top_k=profile.top_k,
        tools=[
            tools.get_system_status,
            tools.check_proxmox_infrastructure,
            tools.list_my_files,
            tools.list_project_files,
            tools.set_monthly_budget_tool,
            tools.get_budget_tool,
            tools.add_recurring_expense_tool,
            tools.list_recurring_expenses_tool,
            tools.get_daily_api_cost_tool,
            tools.get_ticker_price_tool,
            tools.get_market_news_tool,
            tools.prediction_market_scan_tool,
            tools.advanced_execution_tool,
            tools.smart_read,
            tools.summarize_pdf,
            tools.summarize_document
        ],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode="AUTO"
            )
        )
    )


def _encode_image_to_base64(image_path: str) -> str:
    """Encode an image file to base64 string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _get_mime_type(image_path: str) -> str:
    """Get MIME type based on file extension."""
    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return mime_map.get(ext, "image/jpeg")


def get_last_topic() -> str:
    """Extract the subject/topic from the last 3 messages for anaphora resolution.
    
    Returns a short summary of what was being discussed.
    """
    try:
        history = chat_history.get_history(limit=6)  # Get last 3 exchanges (user + assistant)
        if len(history) < 2:
            return ""
        
        # Get last 3 user messages
        user_messages = [h['content'] for h in history if h['role'] == 'user'][-3:]
        
        if not user_messages:
            return ""
        
        # Simple topic extraction: combine last messages
        topic = " | ".join(user_messages)
        return topic[:200]  # Limit length
    except Exception as e:
        logger.error(f"Failed to get last topic: {e}")
        return ""

def process_chat(
    message: str,
    image_paths: Optional[list[str]] = None,
    persona_override: Optional[str] = None,
) -> str:
    """Processes a chat message with 3-tier memory injection.

    MEMORY FLOW:
    1. Pre-process: Query all 3 tiers (SQLite, Mem0, JSON)
    2. Inject: Format memory into prompt with [ACTIVE_CONVERSATION_CONTEXT]
    3. Generate: Send to Gemini with full context
    4. Post-process: Store to appropriate memory tiers

    Args:
        message: The text message to process.
        image_paths: Optional list of image file paths for vision analysis.
        persona_override: Optional persona key to force for this call.

    DEPRECATED: Use `kuro_backend.langgraph_core.process_chat_with_graph*`
    for new code. Legacy callers (CLI, tests) continue to work unchanged.
    """
    try:
        # === PRE-PROCESS: Query Memory (3-Tier with V3.0 Contextual RAG) ===
        # Get recent messages for query expansion
        active_persona = memory_manager.normalize_persona(persona_override or memory_manager.get_active_persona())
        recent_messages = memory_manager.get_short_term(persona_scope=active_persona)
        memory = memory_manager.query_memory(message, recent_messages=recent_messages, persona_scope=active_persona)
        
        # === ACTIVE CONVERSATION CONTEXT (Priority 1 for Anaphora Resolution) ===
        short_term = memory.get("short_term", "")
        last_topic = get_last_topic()
        
        active_context = ""
        if short_term:
            active_context = f"\n\n[ACTIVE_CONVERSATION_CONTEXT - PRIORITY 1]\n{short_term}"
        if last_topic:
            active_context += f"\n\n[LAST_TOPIC: {last_topic}]"
        
        # === BUILD PROMPT WITH MEMORY INJECTION ===
        full_message = f"{message}{active_context}{memory_injection}"
        
        # Add override message if Tier 3 is absolute truth
        if override["override_applied"]:
            full_message += f"\n\n{override['message']}"
        
        # Add confidence-based disclaimer
        if confidence["disclaimer"]:
            full_message += f"\n\n{confidence['disclaimer']}"
        
        # Add verification note if info found in multiple tiers
        if len(verification["found_in_tiers"]) >= 2:
            full_message += f"\n\n[VERIFIKASI: Informasi ditemukan di {len(verification['found_in_tiers'])} sumber memori - kemungkinan akurat.]"
        
        # === BUILD CONTENTS FOR MULTI-MODAL INPUT ===
        contents_parts = []
        contents_parts.append(types.Part(text=full_message))
        
        # Add image parts if any (Vision support)
        if image_paths:
            for img_path in image_paths:
                if os.path.exists(img_path):
                    mime_type = _get_mime_type(img_path)
                    image_data = _encode_image_to_base64(img_path)
                    contents_parts.append(types.Part(
                        inline_data=types.Blob(
                            mime_type=mime_type,
                            data=image_data
                        )
                    ))
                    logger.info(f"Added image to request: {img_path}")

        # === GENERATE CONTENT WITH STRICT V3 PROTOCOL ===
        response = client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=contents_parts,
            config=_get_generation_config(persona_override=active_persona)  # Dynamic config with current time
        )

        # SAFETY CHECK: Check prompt_feedback BEFORE accessing response.text
        # When content is blocked by safety filters, response.text raises AttributeError
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
            block_reason = getattr(response.prompt_feedback, 'block_reason', 'UNKNOWN')
            logger.warning(f"[CORE] Content blocked by safety filter: {block_reason}")
            response_text = "Maaf, Pantronux. Respons diblokir oleh filter keamanan Gemini. Silakan ubah pertanyaan Anda."
        else:
            try:
                response_text = response.text if response.text else "Maaf, Pantronux. Kuro tidak dapat menghasilkan respons yang valid."
            except Exception as text_err:
                if "WARNING" in str(text_err) or "Safety" in str(text_err) or "blocked" in str(text_err).lower():
                    logger.warning(f"[CORE] response.text blocked: {text_err}")
                    response_text = "Maaf, Pantronux. Respons diblokir oleh filter keamanan Gemini."
                else:
                    raise text_err

        # === POST-PROCESS: Store to Memory Tiers ===
        # Tier 1: Always store to short-term (SQLite)
        memory_manager.add_short_term("user", message, persona_scope=active_persona)
        memory_manager.add_short_term("assistant", response_text, persona_scope=active_persona)
        
        # Tier 2: Store to long-term with V2.1 Semantic Upsert
        memory_manager.add_long_term_v2(f"User: {message}\nKuro: {response_text}")
        
        # If there are file attachments, store file content to Mem0 for semantic search
        if image_paths:
            for img_path in image_paths:
                if os.path.exists(img_path):
                    memory_manager.add_long_term_v2(
                        f"User uploaded image: {os.path.basename(img_path)}",
                        metadata={"type": "image", "filename": os.path.basename(img_path), "path": img_path}
                    )
                    logger.info(f"Stored image reference in Mem0: {img_path}")
        
        # Check for explicit memory commands
        if any(kw in message.lower() for kw in memory_manager.MEMORY_KEYWORDS):
            memory_manager.add_long_term_v2(message)
            logger.info(f"Explicit memory command detected: {message[:50]}...")
        
        # === MEMORY V2.1: Conversation Summarization ===
        memory_manager.summarize_conversation_to_chroma()
        
        # === MEMORY V2.1: Auto-Save Master Facts with Classification ===
        saved_facts = memory_manager.detect_and_save_master_facts(message, response_text)
        if saved_facts:
            logger.info(f"Auto-saved {len(saved_facts)} master facts with V2.1 classification")
        
        # === MEMORY V2.1: Sync Mem0 to Profile (auto-migration) ===
        migrated = memory_manager.sync_chroma_to_profile()
        if migrated:
            logger.info(f"Auto-migrated {len(migrated)} facts to master_profile.json")

        return response_text

    except ClientError as e:
        logger.error(f"ClientError in process_chat: {e}")
        return f"Maaf, Pantronux. Terjadi kesalahan konfigurasi pada permintaan Anda: {e}"

    except APIError as e:
        logger.error(f"APIError in process_chat: {e}")
        return "Maaf, Pantronux. Layanan Gemini AI sedang tidak tersedia atau mengalami gangguan. Silakan coba beberapa saat lagi."

    except Exception as e:
        logger.exception(f"Unexpected error in process_chat: {e}")
        return "Maaf, Pantronux. Butler Kuro mengalami kendala tak terduga. Silakan coba lagi."
