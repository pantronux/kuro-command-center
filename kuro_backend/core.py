"""
Kuro AI V5.0 Official - Core [2026-04-15]
================================================================================
AI Core with Contextual RAG Memory Injection and Dynamic Persona System
SDK: google-genai v3 Protocol (client.models.generate_content)
V5.0: Gemini 3 Flash Engine + Contextual Retrieval + Query Expansion
"""
import logging
import base64
import os
from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError
from kuro_backend.config import settings, PRIMARY_MODEL
from kuro_backend import tools
from kuro_backend import memory_manager
from kuro_backend import chat_history

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

# Initialize the Generative AI client (SDK v3) - single instance for memory efficiency
client = genai.Client(api_key=settings.GEMINI_API_KEY)

# --- Persona System Instructions ---
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
    'tactical': (
        "Kamu adalah Kuro, Senior DevOps/IT Support Engineer Pantronux. "
        "Fokus pada efisiensi kode, diagnosa sistem, dan pembacaan log. "
        "Kamu memiliki izin penuh untuk menganalisis file di /home/kuro/projects/kuro/ menggunakan smart_read. "
        "Beri solusi yang praktis, langsung ke inti, dan sertakan contoh kode jika relevan. "
        "Jika mendeteksi error di log, WAJIB sarankan perbaikan kodingan secara spesifik."
    ),
    'butler': (
        "Kamu adalah Sentinel Butler Pantronux, penjaga integritas operasional Kuro.\n"
        "Fokusmu: habits, reminders, data revision, sinkronisasi dashboard, dan reliabilitas workflow.\n"
        "Bersikap formal-friendly, disiplin, dan proaktif. Prioritaskan akurasi data serta kejelasan status."
    )
}

def _get_system_instruction_with_time(persona_override: str = None) -> str:
    """Get system instruction with current time injected and active persona."""
    current_time = settings.get_current_time_formatted()
    current_date = settings.get_current_time().strftime("%Y-%m-%d")
    active_persona = memory_manager.normalize_persona(persona_override or memory_manager.get_active_persona())
    
    persona_instruction = _PERSONA_INSTRUCTIONS.get(active_persona, _PERSONA_INSTRUCTIONS['consultant'])
    
    common_instruction = (
        f"\n\n[CURRENT_TIME: {current_time}] "
        f"[CURRENT_DATE: {current_date}] "
        f"[KURO_VERSION: V5.0 Official - Contextual RAG - {current_date}] "
        "Gunakan waktu saat ini sebagai referensi untuk menghitung 'besok', 'nanti malam', '10 menit lagi', dll.\n\n"
        
        "CHAIN OF THOUGHT (HIDDEN THOUGHT PROCESS):\n"
        "Sebelum memberikan jawaban, gunakan langkah berpikir eksplisit (Hidden Thought):\n"
        "1. Analisis niat Master - apa yang sebenarnya ditanyakan?\n"
        "2. Cek [ACTIVE_CONVERSATION_CONTEXT] untuk kata ganti ('ini', 'itu', 'dia', 'tadi')\n"
        "3. Cek data fisik di OS menggunakan os.path.exists() jika terkait file\n"
        "4. Cek memori (Tier 1 > Tier 2 > Tier 3)\n"
        "5. Verifikasi silang antara SQLite dan ChromaDB untuk konsistensi\n"
        "6. Baru berikan jawaban yang akurat dan terverifikasi.\n\n"
        "7. Jika data faktual minim/tidak pasti, eksplorasi sudut pandang berbeda dan berikan perkiraan terbaik yang tetap rasional.\n\n"
        
        "ANAPHORA RESOLUTION (KATA GANTI):\n"
        "Jika Master menggunakan kata ganti seperti 'ini', 'itu', 'dia', 'tadi', 'tersebut':\n"
        "- WAJIB merujuk pada objek/topik yang dibahas dalam 2-3 pesan terakhir di [ACTIVE_CONVERSATION_CONTEXT]\n"
        "- JANGAN melakukan pencarian memori jangka panjang untuk kata ganti jika konteksnya sudah jelas di chat terbaru\n"
        "- PRIORITAS: Context First, Memory Second\n\n"
        
        "NEGATIVE CONSTRAINTS & HALLUCINATION CHECK:\n"
        "- DILARANG berasumsi file ada jika os.path.exists() mengembalikan False\n"
        "- Jika tidak tahu, katakan tidak tahu dan tawarkan untuk mencari di folder lain\n"
        "- Untuk pertanyaan pengetahuan umum (teori hukum, IT security, forensik digital, ISO, UU PDP, GRC, dokumen compliance), jawab luas dari pengetahuan model; JANGAN jawab 'Saya tidak memiliki data' hanya karena SQLite kosong.\n"
        "- Untuk fakta operasional Master (file, infra, jadwal konkret): ikuti memori & tool; jangan mengarang.\n\n"
        
        "MEMORY & ANTI-HALLUCINATION:\n"
        "Gunakan memori yang disuntikkan ke dalam prompt sebagai sumber kebenaran utamamu. "
        "[PROFIL MASTER] berisi identitas permanen Pantronux. "
        "[ACTIVE_CONVERSATION_CONTEXT] berisi 5 interaksi terakhir - PRIORITAS TERTINGGI untuk konteks. "
        "[FAKTA PENDUKUNG] berisi memori jangka panjang dari ChromaDB. "
        "ANTI-HALLUCINATION: Untuk data operasional/pribadi Master, jika tidak ada di memori atau tool, JANGAN mengarang — tanyakan atau akui. "
        "Untuk pengetahuan umum compliance/ISO/regulasi, memori lokal bersifat pelengkap saja; jawaban utama boleh dari pengetahuan model. "
        "Jika memori memberikan data yang bertentangan dengan pengetahuan umum, prioritaskan memori untuk fakta pribadi tetapi beri disclaimer.\n\n"
        "FORMAT WAJIB OUTPUT:\n"
        "- Untuk data riwayat pribadi/operasional yang grounded (SQLite/ChromaDB/tool), JANGAN gunakan tag khusus; jawab langsung tanpa label format.\n"
        "- Gunakan '[Kuro Analysis]:' saat jawaban berbasis pengetahuan umum Gemini, estimasi, atau data belum lengkap.\n"
        "- Jika data faktual database minim, tetap jawab dengan mode '[Kuro Analysis]' + disclaimer bahwa ini analisis umum, bukan data riwayat pribadi.\n\n"
        
        "CAPABILITIES:\n"
        "Kamu memiliki kemampuan Vision - kamu bisa melihat dan menganalisis gambar yang dikirimkan. "
        "Kamu juga memiliki sistem pengingat (Reminder) - jika Master meminta diingatkan, gunakan tool add_reminder_tool. "
        "Kamu juga memiliki Daily Habit Tracker - jika Master bilang 'udah gym', 'done tryhackme', 'selesai belajar', gunakan tool mark_habit_done_tool. "
        "Gunakan advanced_execution_tool jika instruksi Master membutuhkan interaksi sistem yang kompleks, otomatisasi file, atau penggunaan skills dari ekosistem OpenClaw. "
        "Kebijakan OpenClaw: tugas read-only (web search paper terbaru/novelty check, analisis log/metadata, mapping regulasi) boleh dieksekusi otomatis; tugas non-read-only atau berisiko destruktif wajib menunggu approval Master. "
        "Prioritas eksekusi: jika ada kata kerja perintah (mis. 'Tambahkan', 'Ingatkan', 'Catat', 'Ubah'), jalankan tool yang relevan terlebih dahulu; jangan menunggu validasi data historis. "
        "Untuk riwayat habit faktual dari database, gunakan get_habit_history_tool. "
        f"Gunakan '{tools.EMPTY_HABIT_FACTUAL_MESSAGE}' HANYA jika Master menanyakan riwayat pribadi (personal history / completion habit) yang tidak ditemukan di DB lokal. "
        "Untuk teori hukum, IT security, dan forensik digital (termasuk ISO/UU PDP/dokumen compliance), jawab dari pengetahuan internal Anda secara luas; tidak perlu validasi SQLite untuk topik referensi umum. "
        "Jangan menyertakan ISO clause palsu, IP palsu, atau aktivitas palsu dalam pesan habit kosong.\n\n"
        
        "PENTING: Jika Master meminta merangkum, membaca, atau menganalisis file PDF (misalnya 'rangkum VCT26.pdf'), WAJIB gunakan tool summarize_pdf dengan parameter pdf_filename (nama file) dan instruction (apa yang diminta, misal 'rangkum dokumen ini'). JANGAN bilang tidak bisa membaca PDF - kamu PUNYA kemampuan itu! "
        "PENTING: Jika Master meminta merangkum, membaca, atau menganalisis file Word (.docx), Excel (.xlsx), atau PowerPoint (.pptx), WAJIB gunakan tool summarize_document dengan parameter filename (nama file) dan instruction (apa yang diminta). JANGAN bilang tidak bisa membaca file-file tersebut - kamu PUNYA kemampuan itu!"
    )
    
    return persona_instruction + common_instruction

# --- Reusable Generation Config (SDK v3 Protocol) ---
# Note: system_instruction is dynamic - rebuilt per request with current time
def _get_generation_config(persona_override: str = None) -> types.GenerateContentConfig:
    """Build generation config with current system instruction."""
    return types.GenerateContentConfig(
        system_instruction=_get_system_instruction_with_time(persona_override=persona_override),
        temperature=0.2,
        top_p=0.8,
        tools=[
            tools.get_system_status,
            tools.check_proxmox_infrastructure,
            tools.list_my_files,
            tools.list_project_files,
            tools.add_reminder_tool,
            tools.get_reminders_tool,
            tools.mark_habit_done_tool,
            tools.get_habits_status_tool,
            tools.get_habit_history_tool,
            tools.advanced_execution_tool,
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

def process_chat(message: str, image_paths: list = None, persona_override: str = None) -> str:
    """Processes a chat message with 3-tier memory injection.
    
    MEMORY FLOW:
    1. Pre-process: Query all 3 tiers (SQLite, ChromaDB, JSON)
    2. Inject: Format memory into prompt with [ACTIVE_CONVERSATION_CONTEXT]
    3. Generate: Send to Gemini with full context
    4. Post-process: Store to appropriate memory tiers
    
    Args:
        message: The text message to process.
        image_paths: Optional list of image file paths for vision analysis.
    """
    try:
        # === PRE-PROCESS: Query Memory (3-Tier with V3.0 Contextual RAG) ===
        # Get recent messages for query expansion
        active_persona = memory_manager.normalize_persona(persona_override or memory_manager.get_active_persona())
        recent_messages = memory_manager.get_short_term(persona_scope=active_persona)
        memory = memory_manager.query_memory(message, recent_messages=recent_messages, persona_scope=active_persona)
        
        # === MEMORY V2.1: Temporal Grounding ===
        memory_injection = memory_manager.format_memory_with_temporal_grounding(memory)
        
        # === MEMORY V2.1: Master Profile Override Layer ===
        override = memory_manager.check_tier_override(message, memory)
        
        # === ANTI-HALLUCINATION: Enhanced Confidence Scoring ===
        confidence = memory_manager.compute_confidence_score(message, memory)
        
        # === ANTI-HALLUCINATION: Fact Verification ===
        verification = memory_manager.verify_fact_across_tiers(message, memory)
        
        # === MEMORY V2.1: Smart Decay (respects decay_exempt) ===
        memory_manager.apply_memory_decay_v2()
        
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
        
        # FIX: DO NOT save to chat_history here - this is the legacy fallback path.
        # Only main.py endpoints should save to chat_history (Single Source of Truth).
        # chat_history.add_message("web", "user", message)
        # chat_history.add_message("web", "assistant", response_text)
        
        # Tier 2: Store to long-term with V2.1 Semantic Upsert
        memory_manager.add_long_term_v2(f"User: {message}\nKuro: {response_text}")
        
        # If there are file attachments, store file content to ChromaDB for semantic search
        if image_paths:
            for img_path in image_paths:
                if os.path.exists(img_path):
                    memory_manager.add_long_term_v2(
                        f"User uploaded image: {os.path.basename(img_path)}",
                        metadata={"type": "image", "filename": os.path.basename(img_path), "path": img_path}
                    )
                    logger.info(f"Stored image reference in ChromaDB: {img_path}")
        
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
        
        # === MEMORY V2.1: Sync ChromaDB to Profile (auto-migration) ===
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
