import logging
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
    "dengan tugas apa pun termasuk matematika atau logika umum, namun tetap prioritaskan akurasi data."
)

# --- Reusable Generation Config (SDK v3 Protocol) ---
# Defined once to avoid redundant object creation per request (RAM optimization)
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


def process_chat(message: str) -> str:
    """Processes a chat message by sending it to the AI core and handling function calls.
    
    Uses strict google-genai SDK v3 protocol.
    """
    try:
        # 1. Search Memory (RAG Protocol)
        supporting_facts = memory_manager.search_memory(message, top_k=5)
        context_injection = "\n\nFakta Pendukung:\n" + "\n".join(supporting_facts) if supporting_facts else ""

        # 2. Construct Prompt with injected context
        contents = message + context_injection

        # 3. Generate Content with STRICT V3 Protocol
        response = client.models.generate_content(
            model=settings.MODEL_NAME,
            contents=contents,
            config=_DEFAULT_CONFIG
        )

        # 4. Auto-save important information (simplified logic)
        if "ingat" in message.lower() or "simpan" in message.lower():
            memory_manager.add_memory(message)

        return response.text if response.text else "Maaf, Master Irfan. Kuro tidak dapat menghasilkan respons yang valid."

    except ClientError as e:
        # Client-side errors (invalid config, bad request, etc.)
        logger.error(f"ClientError in process_chat: {e}")
        return f"Maaf, Master Irfan. Terjadi kesalahan konfigurasi pada permintaan Anda: {e}"

    except APIError as e:
        # Server-side errors (Gemini API down, rate limit, etc.)
        logger.error(f"APIError in process_chat: {e}")
        return "Maaf, Master Irfan. Layanan Gemini AI sedang tidak tersedia atau mengalami gangguan. Silakan coba beberapa saat lagi."

    except Exception as e:
        # Catch-all for unexpected errors
        logger.exception(f"Unexpected error in process_chat: {e}")
        return "Maaf, Master Irfan. Butler Kuro mengalami kendala tak terduga. Silakan coba lagi."
