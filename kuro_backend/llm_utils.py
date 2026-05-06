import logging
import json
from kuro_backend.config import settings
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)
genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)

def generate_chat_title(message_text: str) -> str:
    """Generate a short 3-5 word title for a chat session based on the first message."""
    try:
        prompt = f"""Buat judul singkat maksimal 3-5 kata untuk chat yang dimulai dengan pesan ini:
'{message_text}'

Ketentuan:
- Bahasa Indonesia (kecuali jika pesan menggunakan bahasa Inggris).
- Sangat singkat (3-5 kata).
- Jangan gunakan tanda kutip di awal/akhir.
- Contoh: "Analisis Ekonomi Makro", "Riset Dissertation", "Diskusi Keamanan Sistem".
"""
        response = genai_client.models.generate_content(
            model=settings.PRIMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=20
            )
        )
        title = response.text.strip().replace('"', '')
        # Ensure it's not too long
        words = title.split()
        if len(words) > 6:
            title = " ".join(words[:5])
        return title or "New Chat"
    except Exception as e:
        logger.error(f"Failed to generate chat title: {e}")
        return "New Chat"


def generate_chat_context_summary(conversation_text: str) -> str:
    """
    Generate a compact chat context summary using Gemini.
    Used by memory_coordinator.generate_chat_context() as the LLM call helper.

    Args:
        conversation_text: Formatted conversation history text (max ~15k chars)

    Returns:
        A structured JSON string with topic, decisions, entities, open_questions, technical_specs.
    """
    import os
    try:
        # Use KURO_CHAT_CONTEXT_MODEL env if set, otherwise gemini-3-flash-preview
        model_name = os.getenv("KURO_CHAT_CONTEXT_MODEL", "gemini-3-flash-preview")
        prompt = (
            "Anda adalah summarizer percakapan. Rangkum percakapan berikut "
            "dalam Bahasa Indonesia dengan format JSON berikut:\n"
            "{\n"
            '  "topic": "topik utama percakapan",\n'
            '  "decisions": ["keputusan yang diambil"],\n'
            '  "entities": ["entitas/istilah penting yang disebut"],\n'
            '  "open_questions": ["pertanyaan yang belum terjawab"],\n'
            '  "technical_specs": ["spesifikasi teknis jika ada"]\n'
            "}\n\n"
            "DILARANG menambah fakta yang tidak ada dalam percakapan.\n"
            f"Percakapan:\n{conversation_text}"
        )
        response = genai_client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                top_p=0.1,
                top_k=1,
                max_output_tokens=384,
                response_mime_type="application/json",
            ),
        )
        raw = getattr(response, "text", "") or "{}"
        return raw.strip()
    except Exception as e:
        logger.error(f"Failed to generate chat context summary: {e}")
        return "{}"
