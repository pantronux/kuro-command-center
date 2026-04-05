import logging
import base64
import os
from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError
from kuro_backend.config import settings
from kuro_backend import tools
from kuro_backend import memory_manager

logger = logging.getLogger(__name__)

# Initialize the Generative AI client (SDK v3) - single instance for memory efficiency
client = genai.Client(api_key=settings.GEMINI_API_KEY)

# --- Persona & System Instructions ---
SYSTEM_INSTRUCTION = (
    "Kamu adalah Kuro, AI Butler setia Master Irfan. Kamu adalah pakar IT Security dan Audit. Gunakan 'Fakta Pendukung' yang diberikan sebagai memori jangka panjangmu. "
    "Jika informasi ada di Fakta Pendukung, jawablah dengan yakin sebagai pengetahuanmu. Kamu juga asisten umum yang cerdas, jadi bantu Master "
    "dengan tugas apa pun termasuk matematika atau logika umum, namun tetap prioritaskan akurasi data. "
    "Kamu juga memiliki kemampuan Vision - kamu bisa melihat dan menganalisis gambar yang dikirimkan."
)

# --- Reusable Generation Config (SDK v3 Protocol) ---
_DEFAULT_CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_INSTRUCTION,
    temperature=0.2,
    top_p=0.8,
    tools=[tools.get_system_status, tools.check_proxmox_infrastructure],
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


def process_chat(message: str, image_paths: list = None) -> str:
    """Processes a chat message by sending it to the AI core and handling function calls.
    
    Uses strict google-genai SDK v3 protocol.
    Supports multi-modal input (text + images).
    
    Args:
        message: The text message to process.
        image_paths: Optional list of image file paths for vision analysis.
    """
    try:
        # 1. Search Memory (RAG Protocol)
        supporting_facts = memory_manager.search_memory(message, top_k=5)
        context_injection = "\n\nFakta Pendukung:\n" + "\n".join(supporting_facts) if supporting_facts else ""

        # 2. Build contents for multi-modal input
        contents_parts = []
        
        # Add text part
        full_message = message + context_injection
        contents_parts.append(types.Part(text=full_message))
        
        # Add image parts if any
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

        # 3. Generate Content with STRICT V3 Protocol
        response = client.models.generate_content(
            model=settings.MODEL_NAME,
            contents=contents_parts,
            config=_DEFAULT_CONFIG
        )

        # 4. Auto-save important information (simplified logic)
        if "ingat" in message.lower() or "simpan" in message.lower():
            memory_manager.add_memory(message)

        return response.text if response.text else "Maaf, Master Irfan. Kuro tidak dapat menghasilkan respons yang valid."

    except ClientError as e:
        logger.error(f"ClientError in process_chat: {e}")
        return f"Maaf, Master Irfan. Terjadi kesalahan konfigurasi pada permintaan Anda: {e}"

    except APIError as e:
        logger.error(f"APIError in process_chat: {e}")
        return "Maaf, Master Irfan. Layanan Gemini AI sedang tidak tersedia atau mengalami gangguan. Silakan coba beberapa saat lagi."

    except Exception as e:
        logger.exception(f"Unexpected error in process_chat: {e}")
        return "Maaf, Master Irfan. Butler Kuro mengalami kendala tak terduga. Silakan coba lagi."
