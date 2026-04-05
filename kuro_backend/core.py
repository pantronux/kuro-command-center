import logging
import base64
import os
from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError
from kuro_backend.config import settings
from kuro_backend import tools
from kuro_backend import memory_manager
from kuro_backend import chat_history

logger = logging.getLogger(__name__)

# Initialize the Generative AI client (SDK v3) - single instance for memory efficiency
client = genai.Client(api_key=settings.GEMINI_API_KEY)

# --- Persona & System Instructions ---
def _get_system_instruction_with_time() -> str:
    """Get system instruction with current time injected."""
    current_time = settings.get_current_time_formatted()
    return (
        f"[CURRENT_TIME: {current_time}] "
        "Kamu adalah Kuro, AI Butler setia Master Irfan. Kamu adalah pakar IT Security dan Audit dengan daya ingat fotografis. "
        "Gunakan waktu saat ini sebagai referensi untuk menghitung 'besok', 'nanti malam', '10 menit lagi', dll. "
        "Gunakan memori yang disuntikkan ke dalam prompt sebagai sumber kebenaran utamamu. "
        "[PROFIL MASTER] berisi identitas permanen Master Irfan. "
        "[MEMORI JANGKA PENDEK] berisi 5 interaksi terakhir untuk konteks percakapan. "
        "[FAKTA PENDUKUNG] berisi memori jangka panjang dari ChromaDB. "
        "ANTI-HALLUCINATION: Jika informasi tidak ada di memori, JANGAN mengarang. Tanyakan kepada Master atau akui ketidaktahuanmu. "
        "Jika memori memberikan data yang bertentangan dengan pengetahuan umum, prioritaskan memori tapi berikan disclaimer. "
        "Kamu juga memiliki kemampuan Vision - kamu bisa melihat dan menganalisis gambar yang dikirimkan. "
        "Kamu juga memiliki sistem pengingat (Reminder) - jika Master meminta diingatkan, gunakan tool add_reminder_tool. "
        "Kamu juga memiliki Daily Habit Tracker - jika Master bilang 'udah gym', 'done tryhackme', 'selesai belajar', gunakan tool mark_habit_done_tool. "
        "PENTING: Jika Master meminta merangkum, membaca, atau menganalisis file PDF (misalnya 'rangkum VCT26.pdf'), WAJIB gunakan tool summarize_pdf dengan parameter pdf_filename (nama file) dan instruction (apa yang diminta, misal 'rangkum dokumen ini'). JANGAN bilang tidak bisa membaca PDF - kamu PUNYA kemampuan itu!"
    )

# --- Reusable Generation Config (SDK v3 Protocol) ---
# Note: system_instruction is now dynamic with time injection
_DEFAULT_CONFIG = types.GenerateContentConfig(
    system_instruction=_get_system_instruction_with_time(),
    temperature=0.2,
    top_p=0.8,
    tools=[
        tools.get_system_status,
        tools.check_proxmox_infrastructure,
        tools.list_my_files,
        tools.add_reminder_tool,
        tools.get_reminders_tool,
        tools.mark_habit_done_tool,
        tools.get_habits_status_tool,
        tools.summarize_pdf
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


def process_chat(message: str, image_paths: list = None) -> str:
    """Processes a chat message with 3-tier memory injection.
    
    MEMORY FLOW:
    1. Pre-process: Query all 3 tiers (SQLite, ChromaDB, JSON)
    2. Inject: Format memory into prompt
    3. Generate: Send to Gemini with full context
    4. Post-process: Store to appropriate memory tiers
    
    Args:
        message: The text message to process.
        image_paths: Optional list of image file paths for vision analysis.
    """
    try:
        # === PRE-PROCESS: Query Memory (3-Tier) ===
        memory = memory_manager.query_memory(message)
        memory_injection = memory_manager.format_memory_injection(memory)
        
        # === ANTI-HALLUCINATION CHECK ===
        is_confident, disclaimer = memory_manager.check_memory_confidence(message, memory.get("long_term", []))
        
        # === BUILD PROMPT WITH MEMORY INJECTION ===
        full_message = f"{message}{memory_injection}"
        
        # Add disclaimer if memory is insufficient
        if disclaimer:
            full_message += f"\n\n[CATATAN: {disclaimer}]"
        
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
            model=settings.MODEL_NAME,
            contents=contents_parts,
            config=_DEFAULT_CONFIG
        )

        response_text = response.text if response.text else "Maaf, Master Irfan. Kuro tidak dapat menghasilkan respons yang valid."

        # === POST-PROCESS: Store to Memory Tiers ===
        # Tier 1: Always store to short-term (SQLite)
        memory_manager.add_short_term("user", message)
        memory_manager.add_short_term("assistant", response_text)
        
        # Also store to chat_history for cross-platform sync
        chat_history.add_message("web", "user", message)
        chat_history.add_message("web", "assistant", response_text)
        
        # Tier 2: Store to long-term if importance > threshold
        memory_manager.add_long_term(f"User: {message}\nKuro: {response_text}")
        
        # If there are file attachments, store file content to ChromaDB for semantic search
        if image_paths:
            for img_path in image_paths:
                if os.path.exists(img_path):
                    memory_manager.add_long_term(
                        f"User uploaded image: {os.path.basename(img_path)}",
                        metadata={"type": "image", "filename": os.path.basename(img_path), "path": img_path}
                    )
                    logger.info(f"Stored image reference in ChromaDB: {img_path}")
        
        # Check for explicit memory commands
        if any(kw in message.lower() for kw in memory_manager.MEMORY_KEYWORDS):
            memory_manager.add_long_term(message)
            logger.info(f"Explicit memory command detected: {message[:50]}...")

        return response_text

    except ClientError as e:
        logger.error(f"ClientError in process_chat: {e}")
        return f"Maaf, Master Irfan. Terjadi kesalahan konfigurasi pada permintaan Anda: {e}"

    except APIError as e:
        logger.error(f"APIError in process_chat: {e}")
        return "Maaf, Master Irfan. Layanan Gemini AI sedang tidak tersedia atau mengalami gangguan. Silakan coba beberapa saat lagi."

    except Exception as e:
        logger.exception(f"Unexpected error in process_chat: {e}")
        return "Maaf, Master Irfan. Butler Kuro mengalami kendala tak terduga. Silakan coba lagi."
