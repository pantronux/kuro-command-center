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
