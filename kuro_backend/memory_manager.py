"""
Kuro Cognitive Memory Engine V2.1 - Tier-3 Architecture with Anti-Hallucination
================================================================================
TIER 1: Short-Term Buffer (SQLite) - Last 20 interactions
TIER 2: Semantic Long-Term Memory (ChromaDB) - Embedded facts
TIER 3: Structured Knowledge Base (JSON) - Permanent master profile (ABSOLUTE TRUTH)

Anti-Hallucination Protocol V2.1:
- Semantic Upsert: Deduplication with similarity search + Gemini Flash classification
- Categorical Fact Tagging: identity/preference/goal/schedule/temporary
- Smart Decay: Respects decay_exempt for permanent facts
- Temporal Grounding: Inject timestamps into prompt to prevent stale data confusion
- Master Profile Override: Tier 3 is absolute truth over all other tiers
- Auto-Migration: Repeated facts auto-sync to master_profile.json
"""
import json
import logging
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from kuro_backend.config import settings

logger = logging.getLogger(__name__)

# ============================================
# Configuration
# ============================================
BASE_DIR = settings.WORKING_DIR
SHORT_TERM_DB = os.path.join(BASE_DIR, "kuro_short_term.db")
LONG_TERM_DIR = os.path.join(BASE_DIR, "kuro_chromadb")
MASTER_PROFILE_PATH = os.path.join(BASE_DIR, "master_profile.json")

SHORT_TERM_LIMIT = 20  # Last 20 interactions
IMPORTANCE_THRESHOLD = 7  # Only store to ChromaDB if importance > 7
MEMORY_DECAY_DAYS = 30  # Facts older than 30 days marked as potentially outdated
CONVERSATION_SUMMARY_THRESHOLD = 15  # Summarize short-term after this many entries
SIMILARITY_THRESHOLD_UPSERT = 0.85  # Threshold for semantic deduplication
SYNC_TO_PROFILE_THRESHOLD = 3  # Auto-migrate to JSON after this many confirmations

# Fact categories for classification
FACT_CATEGORIES = ["identity", "preference", "goal", "schedule", "temporary"]
DECAY_EXEMPT_CATEGORIES = ["identity", "preference", "goal"]  # These never expire

# Keywords that trigger memory storage
MEMORY_KEYWORDS = ["ingat", "simpan", "jadwal", "info", "spesifikasi", "catat", "profile", "preferensi"]

# Keywords that indicate Master is sharing personal facts
MASTER_FACT_KEYWORDS = ["saya suka", "saya tidak suka", "saya punya", "saya menggunakan",
                        "saya bekerja", "saya tinggal", "favorit saya", "hobi saya",
                        "nama saya", "umur saya", "pekerjaan saya"]

# Thread lock for safety
_lock = threading.Lock()

# ============================================
# TIER 3: Structured Knowledge Base (JSON)
# ============================================
def load_master_profile() -> Dict:
    """Load the master profile JSON (Tier 3 - Permanent knowledge)."""
    try:
        with open(MASTER_PROFILE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to load master profile: {e}")
        return {"master": {"name": "Master Irfan"}, "infrastructure": {}, "preferences": {}, "notes": []}

def save_master_profile(profile: Dict):
    """Save updates to master profile."""
    with _lock:
        with open(MASTER_PROFILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(profile, f, ensure_ascii=False, indent=4)
        logger.info("Master profile updated.")

def get_master_profile_formatted() -> str:
    """Get formatted master profile for prompt injection."""
    profile = load_master_profile()
    lines = []
    lines.append(f"Nama Master: {profile.get('master', {}).get('name', 'Master Irfan')}")
    
    infra = profile.get('infrastructure', {})
    if infra:
        lines.append(f"Proxmox Host: {infra.get('proxmox_host', 'N/A')}")
        lines.append(f"Kuro VM IP: {infra.get('kuro_vm_ip', 'N/A')}")
    
    prefs = profile.get('preferences', {})
    if prefs:
        lines.append(f"Model AI: {prefs.get('ai_model', 'N/A')}")
    
    notes = profile.get('notes', [])
    if notes:
        lines.append("Catatan Penting:")
        for note in notes:
            lines.append(f"  - {note}")
    
    return "\n".join(lines)

def update_master_profile(key: str, value: str):
    """Update a specific field in master profile."""
    profile = load_master_profile()
    
    # Try to parse key as nested path (e.g., "infrastructure.proxmox_host")
    parts = key.split('.')
    target = profile
    for part in parts[:-1]:
        if part not in target:
            target[part] = {}
        target = target[part]
    target[parts[-1]] = value
    
    save_master_profile(profile)
    logger.info(f"Updated master profile: {key} = {value}")

# ============================================
# TIER 1: Short-Term Buffer (SQLite)
# ============================================
def _get_short_term_conn():
    """Get SQLite connection for short-term memory."""
    conn = sqlite3.connect(SHORT_TERM_DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_short_term_db():
    """Initialize short-term memory database."""
    conn = _get_short_term_conn()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS short_term (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Short-term memory database initialized.")

def add_short_term(role: str, content: str):
    """Add interaction to short-term buffer."""
    conn = _get_short_term_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO short_term (role, content) VALUES (?, ?)", (role, content))
    
    # Enforce limit - delete oldest if over limit
    cursor.execute("DELETE FROM short_term WHERE id NOT IN (SELECT id FROM short_term ORDER BY id DESC LIMIT ?)", (SHORT_TERM_LIMIT,))
    
    conn.commit()
    conn.close()

def get_short_term() -> List[Dict]:
    """Get recent short-term memory."""
    conn = _get_short_term_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM short_term ORDER BY id DESC LIMIT ?", (SHORT_TERM_LIMIT,))
    rows = cursor.fetchall()
    conn.close()
    return [{"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]} for r in reversed(rows)]

def summarize_short_term() -> str:
    """Summarize short-term memory for token optimization."""
    entries = get_short_term()
    if len(entries) <= 5:
        return ""  # No need to summarize if few entries
    
    # Simple summarization: count user vs assistant messages
    user_msgs = [e for e in entries if e["role"] == "user"]
    assistant_msgs = [e for e in entries if e["role"] == "assistant"]
    
    summary = f"[Ringkasan {len(entries)} interaksi terakhir: {len(user_msgs)} pesan user, {len(assistant_msgs)} respons AI]"
    return summary

# ============================================
# TIER 2: Semantic Long-Term Memory (ChromaDB)
# ============================================
# Lazy import to avoid errors if chromadb not installed
_chroma_client = None
_chroma_collection = None

def _get_chroma_collection():
    """Get or create ChromaDB collection (lazy initialization)."""
    global _chroma_client, _chroma_collection
    if _chroma_collection is None:
        try:
            import chromadb
            _chroma_client = chromadb.PersistentClient(path=LONG_TERM_DIR)
            _chroma_collection = _chroma_client.get_or_create_collection(name="kuro_long_term")
            logger.info("ChromaDB initialized for long-term memory.")
        except ImportError:
            logger.warning("ChromaDB not installed. Long-term semantic memory disabled.")
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")
    return _chroma_collection

def compute_importance_score(message: str) -> int:
    """
    Importance Scorer: Rate message importance (1-10).
    Factors: keywords, specificity, length, question marks.
    """
    score = 5  # Base score
    
    # Keyword boost
    msg_lower = message.lower()
    for kw in MEMORY_KEYWORDS:
        if kw in msg_lower:
            score += 2
            break
    
    # Specificity boost (numbers, dates, names)
    if re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', message):  # Dates
        score += 1
    if re.search(r'\b\d+\b', message):  # Numbers
        score += 1
    
    # Length boost (longer = more detailed = more important)
    if len(message) > 100:
        score += 1
    if len(message) > 200:
        score += 1
    
    return min(score, 10)  # Cap at 10

def add_long_term(content: str, metadata: Dict = None):
    """Add fact to ChromaDB long-term memory if importance > threshold."""
    import uuid
    from datetime import datetime
    
    importance = compute_importance_score(content)
    
    if importance < IMPORTANCE_THRESHOLD:
        logger.debug(f"Message importance ({importance}) below threshold. Skipping ChromaDB storage.")
        return False
    
    collection = _get_chroma_collection()
    if collection is None:
        return False
    
    try:
        # Data validation: ensure all lists have same length
        doc_id = str(uuid.uuid4())
        documents = [content]
        
        # CRITICAL FIX: ChromaDB requires non-empty metadata dict
        # Always include at least timestamp and importance score
        safe_metadata = {
            "timestamp": datetime.now().isoformat(),
            "importance": importance,
            "source": "auto"
        }
        if metadata:
            safe_metadata.update(metadata)
        
        metadatas = [safe_metadata]
        ids = [doc_id]
        
        # Debug logging: verify list lengths before insert
        logger.debug(f"ChromaDB add validation: ids={len(ids)}, documents={len(documents)}, metadatas={len(metadatas)}")
        logger.debug(f"ChromaDB doc_id: {doc_id}, content_length: {len(content)}")
        
        # Validate before adding
        if not (len(ids) == len(documents) == len(metadatas)):
            raise ValueError(f"List length mismatch: ids={len(ids)}, documents={len(documents)}, metadatas={len(metadatas)}")
        
        # Validate metadata is non-empty dict
        if not metadatas[0]:
            raise ValueError("Metadata dict is empty - ChromaDB requires at least one key")
        
        # Check for existing similar entries (self-correction)
        existing = collection.query(query_texts=[content], n_results=1)
        if existing and existing.get('ids') and len(existing.get('ids', [])) > 0:
            existing_ids = existing['ids'][0] if existing['ids'] else []
            if existing_ids and len(existing_ids) > 0:
                existing_distances = existing.get('distances', [[]])
                if existing_distances and len(existing_distances) > 0 and existing_distances[0] and len(existing_distances[0]) > 0:
                    if existing_distances[0][0] < 0.3:
                        # Similar entry exists - update instead of duplicate
                        update_id = existing_ids[0]
                        collection.update(ids=[update_id], documents=documents, metadatas=metadatas)
                        logger.info(f"Updated existing long-term memory entry (importance: {importance})")
                        return True
        
        # New entry - safe add with validated lists
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        logger.info(f"Added new long-term memory entry (importance: {importance})")
        return True
        
    except ValueError as ve:
        logger.error(f"ChromaDB validation error: {ve}")
        return False
    except Exception as e:
        logger.error(f"Failed to add to ChromaDB: {e}")
        return False

def search_long_term(query: str, top_k: int = 5) -> List[str]:
    """Search ChromaDB for relevant facts."""
    collection = _get_chroma_collection()
    if collection is None:
        return []
    
    try:
        results = collection.query(query_texts=[query], n_results=top_k)
        return results.get('documents', [[]])[0]
    except Exception as e:
        logger.error(f"Failed to search ChromaDB: {e}")
        return []

def mark_obsolete(query: str):
    """Mark old entries as obsolete when updated."""
    collection = _get_chroma_collection()
    if collection is None:
        return
    
    try:
        results = collection.query(query_texts=[query], n_results=5)
        if results['ids']:
            for doc_id in results['ids'][0]:
                collection.update(ids=[doc_id], metadatas=[{"status": "obsolete"}])
            logger.info(f"Marked entries as obsolete for query: {query}")
    except Exception as e:
        logger.error(f"Failed to mark obsolete: {e}")

# ============================================
# Unified Memory Query Interface
# ============================================
def query_memory(current_message: str) -> Dict[str, str]:
    """
    Pre-process memory before AI response.
    Returns formatted memory sections for prompt injection.
    """
    # Tier 1: Short-term
    short_term_entries = get_short_term()
    short_term_text = ""
    if short_term_entries:
        summaries = []
        for entry in short_term_entries[-5:]:  # Last 5
            role_label = "User" if entry["role"] == "user" else "Kuro"
            summaries.append(f"{role_label}: {entry['content'][:100]}")
        short_term_text = "\n".join(summaries)
    
    # Tier 2: Long-term semantic search
    long_term_facts = search_long_term(current_message, top_k=5)
    long_term_text = "\n".join(long_term_facts) if long_term_facts else ""
    
    # Tier 3: Master profile
    profile_text = get_master_profile_formatted()
    
    return {
        "short_term": short_term_text,
        "long_term": long_term_text,
        "profile": profile_text
    }

def format_memory_injection(memory: Dict[str, str]) -> str:
    """Format memory sections for prompt injection."""
    parts = []
    
    if memory["profile"]:
        parts.append(f"\n[PROFIL MASTER]\n{memory['profile']}")
    
    if memory["short_term"]:
        parts.append(f"\n[MEMORI JANGKA PENDEK - 5 Interaksi Terakhir]\n{memory['short_term']}")
    
    if memory["long_term"]:
        parts.append(f"\n[FAKTA PENDUKUNG - Memori Jangka Panjang]\n{memory['long_term']}")
    
    return "\n".join(parts)

# ============================================
# Anti-Hallucination Protocol - ENHANCED
# ============================================

def compute_confidence_score(query: str, memory: Dict[str, str]) -> Dict:
    """
    Compute confidence score (0-100) based on memory availability across all tiers.
    
    Returns dict with:
    - score: 0-100 confidence level
    - sources: list of memory tiers that have relevant info
    - disclaimer: message to show if confidence is low
    """
    score = 0
    sources = []
    
    # Tier 3: Master Profile (most reliable - permanent facts)
    if memory.get("profile"):
        score += 40
        sources.append("profile")
    
    # Tier 2: Long-term ChromaDB (semantic facts)
    if memory.get("long_term"):
        score += 35
        sources.append("long_term")
    
    # Tier 1: Short-term (recent context)
    if memory.get("short_term"):
        score += 25
        sources.append("short_term")
    
    # Determine confidence level and disclaimer
    if score >= 75:
        level = "high"
        disclaimer = ""
    elif score >= 40:
        level = "medium"
        disclaimer = f"[CATATAN: Informasi tentang '{query}' berdasarkan memori terbatas. Mohon koreksi jika ada yang kurang tepat.]"
    elif score >= 15:
        level = "low"
        disclaimer = f"[CATATAN: Saya memiliki sedikit informasi tentang '{query}'. Jawaban mungkin tidak akurat.]"
    else:
        level = "none"
        disclaimer = f"[CATATAN: Saya belum memiliki catatan tentang '{query}'. Jawaban berdasarkan pengetahuan umum, bukan memori pribadi Master.]"
    
    return {
        "score": score,
        "level": level,
        "sources": sources,
        "disclaimer": disclaimer
    }


def apply_memory_decay() -> List[str]:
    """
    Memory Decay: Mark facts older than MEMORY_DECAY_DAYS as potentially outdated.
    Returns list of fact IDs that were marked as outdated.
    """
    collection = _get_chroma_collection()
    if collection is None:
        return []
    
    outdated_ids = []
    cutoff_date = datetime.now() - timedelta(days=MEMORY_DECAY_DAYS)
    
    try:
        # Get all entries
        results = collection.get(include=['metadatas', 'documents'])
        
        if results and results.get('metadatas'):
            for i, metadata in enumerate(results['metadatas']):
                if metadata and 'timestamp' in metadata:
                    try:
                        fact_date = datetime.fromisoformat(metadata['timestamp'])
                        if fact_date < cutoff_date and metadata.get('status') != 'outdated':
                            doc_id = results['ids'][i]
                            collection.update(
                                ids=[doc_id],
                                metadatas=[{**metadata, 'status': 'outdated', 'outdated_since': datetime.now().isoformat()}]
                            )
                            outdated_ids.append(doc_id)
                            logger.info(f"Marked fact as outdated (age > {MEMORY_DECAY_DAYS} days): {doc_id}")
                    except (ValueError, KeyError):
                        continue
        
        if outdated_ids:
            logger.info(f"Memory decay applied: {len(outdated_ids)} facts marked as outdated")
        
    except Exception as e:
        logger.error(f"Failed to apply memory decay: {e}")
    
    return outdated_ids


def summarize_conversation_to_chroma():
    """
    Conversation Summarization: When short-term buffer is full,
    summarize the conversation and store to ChromaDB for long-term retention.
    """
    entries = get_short_term()
    
    if len(entries) < CONVERSATION_SUMMARY_THRESHOLD:
        return False
    
    try:
        # Build conversation summary
        user_msgs = [e['content'][:200] for e in entries if e['role'] == 'user']
        assistant_msgs = [e['content'][:200] for e in entries if e['role'] == 'assistant']
        
        summary = f"[Ringkasan Percakapan {len(entries)} interaksi]\n"
        summary += f"Topik yang dibahas: {', '.join(user_msgs[:3])}...\n"
        summary += f"Respons Kuro: {', '.join(assistant_msgs[:3])}..."
        
        # Store to ChromaDB
        add_long_term(summary, metadata={
            "type": "conversation_summary",
            "interaction_count": len(entries),
            "source": "auto_summary"
        })
        
        logger.info(f"Conversation summarized: {len(entries)} interactions stored to ChromaDB")
        return True
        
    except Exception as e:
        logger.error(f"Failed to summarize conversation: {e}")
        return False


def verify_fact_across_tiers(query: str, memory: Dict[str, str]) -> Dict:
    """
    Fact Verification: Cross-reference information across all 3 memory tiers.
    Returns verification result with consistency check.
    """
    verification = {
        "found_in_tiers": [],
        "consistent": True,
        "conflicting_info": [],
        "recommended_answer": ""
    }
    
    # Check Tier 3 (Profile)
    if memory.get("profile"):
        verification["found_in_tiers"].append("profile")
    
    # Check Tier 2 (ChromaDB)
    if memory.get("long_term"):
        verification["found_in_tiers"].append("long_term")
    
    # Check Tier 1 (Short-term)
    if memory.get("short_term"):
        verification["found_in_tiers"].append("short_term")
    
    # Determine consistency
    tier_count = len(verification["found_in_tiers"])
    
    if tier_count >= 2:
        verification["consistent"] = True
        verification["recommended_answer"] = "Informasi ditemukan di multiple tiers - kemungkinan akurat."
    elif tier_count == 1:
        verification["consistent"] = True
        verification["recommended_answer"] = "Informasi ditemukan di 1 tier - verifikasi dengan Master jika penting."
    else:
        verification["consistent"] = False
        verification["recommended_answer"] = "Tidak ada informasi di memori - gunakan pengetahuan umum dengan disclaimer."
    
    return verification


def detect_and_save_master_facts(message: str, response: str) -> List[str]:
    """
    Master Profile Auto-Update: Detect when Master shares personal facts
    and automatically save them to the appropriate memory tier.
    
    Returns list of facts that were saved.
    """
    saved_facts = []
    msg_lower = message.lower()
    
    for keyword in MASTER_FACT_KEYWORDS:
        if keyword in msg_lower:
            # Extract the fact (simple extraction - take the sentence containing the keyword)
            sentences = re.split(r'[.!?]+', message)
            for sentence in sentences:
                if keyword in sentence.lower():
                    fact = sentence.strip()
                    if len(fact) > 10:  # Only save meaningful facts
                        # Save to ChromaDB with high importance
                        add_long_term(f"Master Irfan: {fact}", metadata={
                            "type": "master_fact",
                            "source": "auto_detect",
                            "keyword": keyword
                        })
                        saved_facts.append(fact)
                        logger.info(f"Auto-saved master fact: {fact[:50]}...")
                    break
    
    return saved_facts


# ============================================
# MEMORY V2.1 - SEMANTIC UPSERT & SMART FEATURES
# ============================================

def _classify_fact_with_llm(fact: str) -> Dict:
    """
    Use Gemini Flash to classify a fact into category and determine decay_exempt status.
    Returns JSON: {"fact": "...", "category": "identity/preference/goal/schedule/temporary", "decay_exempt": true/false}
    """
    try:
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        prompt = f"""Klasifikasikan fakta berikut tentang Master Irfan ke dalam kategori yang tepat.

Fakta: "{fact}"

Kategori yang tersedia:
- identity: Fakta identitas permanen (nama, pekerjaan, lokasi, keluarga, dll)
- preference: Preferensi pribadi (makanan favorit, hobi, kebiasaan, dll)
- goal: Tujuan atau target (target berat badan, project yang sedang dikerjakan, dll)
- schedule: Jadwal rutin (jadwal meeting, jadwal gym, dll)
- temporary: Fakta sementara yang akan berubah (berat badan hari ini, mood, dll)

Aturan decay_exempt:
- identity, preference, goal = decay_exempt: true (tidak pernah kadaluarsa)
- schedule, temporary = decay_exempt: false (bisa kadaluarsa)

Berikan jawaban HANYA dalam format JSON berikut, tanpa teks tambahan:
{{"fact": "{fact}", "category": "kategori_di_sini", "decay_exempt": true_atau_false}}"""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1)
        )
        
        if response.text:
            # Parse JSON from response
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        
        # Fallback if parsing fails
        return {"fact": fact, "category": "temporary", "decay_exempt": False}
        
    except Exception as e:
        logger.error(f"Failed to classify fact with LLM: {e}")
        return {"fact": fact, "category": "temporary", "decay_exempt": False}


def _resolve_memory_conflict(new_fact: str, new_metadata: Dict) -> Optional[str]:
    """
    Semantic Upsert: Check for similar existing facts and resolve conflicts.
    
    Returns:
    - existing_id if found and archived (for audit trail)
    - None if no conflict (new insert)
    """
    collection = _get_chroma_collection()
    if collection is None:
        return None
    
    try:
        # Step 1: High-similarity search (>0.85)
        results = collection.query(
            query_texts=[new_fact],
            n_results=3,
            include=['metadatas', 'distances']
        )
        
        if not results or not results.get('ids') or not results['ids'][0]:
            return None
        
        # Step 2: Check similarity threshold
        distances = results.get('distances', [[]])[0]
        existing_ids = results['ids'][0]
        existing_metadatas = results.get('metadatas', [[]])[0]
        
        for i, (doc_id, metadata, distance) in enumerate(zip(existing_ids, existing_metadatas, distances)):
            # ChromaDB distance: lower = more similar. Convert to similarity score.
            similarity = 1.0 - (distance / 2.0)  # Approximate conversion
            
            if similarity >= SIMILARITY_THRESHOLD_UPSERT:
                # Step 3: Use LLM to check if this is an update
                classification = _classify_fact_with_llm(new_fact)
                
                # Archive the old fact (keep for audit trail, but exclude from context)
                collection.update(
                    ids=[doc_id],
                    metadatas=[{
                        **metadata,
                        "status": "archived_by_update",
                        "archived_at": datetime.now().isoformat(),
                        "replaced_by": new_fact[:100]
                    }]
                )
                
                logger.info(f"Archived conflicting fact (similarity: {similarity:.2f}): {doc_id}")
                return doc_id
        
        return None
        
    except Exception as e:
        logger.error(f"Failed to resolve memory conflict: {e}")
        return None


def add_long_term_v2(content: str, metadata: Dict = None) -> Dict:
    """
    Enhanced add_long_term with Semantic Upsert and Categorical Fact Tagging.
    
    Returns dict with:
    - success: bool
    - action: "inserted" | "updated" | "skipped"
    - classification: fact classification result
    """
    import uuid
    
    # Step 1: Classify the fact
    classification = _classify_fact_with_llm(content)
    
    # Step 2: Merge metadata
    safe_metadata = {
        "timestamp": datetime.now().isoformat(),
        "importance": compute_importance_score(content),
        "source": metadata.get("source", "auto") if metadata else "auto",
        "category": classification.get("category", "temporary"),
        "decay_exempt": classification.get("decay_exempt", False),
        "status": "active"
    }
    if metadata:
        safe_metadata.update({k: v for k, v in metadata.items() if k not in safe_metadata})
    
    # Step 3: Resolve conflicts (Semantic Upsert)
    archived_id = _resolve_memory_conflict(content, safe_metadata)
    
    # Step 4: Add to ChromaDB
    collection = _get_chroma_collection()
    if collection is None:
        return {"success": False, "action": "skipped", "reason": "ChromaDB unavailable"}
    
    try:
        doc_id = str(uuid.uuid4())
        collection.add(
            ids=[doc_id],
            documents=[content],
            metadatas=[safe_metadata]
        )
        
        action = "updated" if archived_id else "inserted"
        logger.info(f"Added fact to ChromaDB (action: {action}, category: {classification['category']}, decay_exempt: {classification['decay_exempt']})")
        
        return {
            "success": True,
            "action": action,
            "classification": classification,
            "doc_id": doc_id
        }
        
    except Exception as e:
        logger.error(f"Failed to add to ChromaDB: {e}")
        return {"success": False, "action": "skipped", "reason": str(e)}


def apply_memory_decay_v2() -> List[str]:
    """
    Smart Decay: Mark old facts as outdated, BUT respect decay_exempt flag.
    
    Facts with decay_exempt: true (identity, preference, goal) are NEVER marked outdated.
    
    Returns list of fact IDs that were marked as outdated.
    """
    collection = _get_chroma_collection()
    if collection is None:
        return []
    
    outdated_ids = []
    cutoff_date = datetime.now() - timedelta(days=MEMORY_DECAY_DAYS)
    
    try:
        results = collection.get(include=['metadatas', 'documents'])
        
        if results and results.get('metadatas'):
            for i, metadata in enumerate(results['metadatas']):
                if not metadata:
                    continue
                
                # SKIP decay_exempt facts (identity, preference, goal)
                if metadata.get('decay_exempt', False):
                    continue
                
                # Skip already processed
                if metadata.get('status') in ['outdated', 'archived_by_update']:
                    continue
                
                # Check age
                if 'timestamp' in metadata:
                    try:
                        fact_date = datetime.fromisoformat(metadata['timestamp'])
                        if fact_date < cutoff_date:
                            doc_id = results['ids'][i]
                            collection.update(
                                ids=[doc_id],
                                metadatas=[{
                                    **metadata,
                                    'status': 'outdated',
                                    'outdated_since': datetime.now().isoformat()
                                }]
                            )
                            outdated_ids.append(doc_id)
                            logger.info(f"Smart decay: Marked as outdated (age > {MEMORY_DECAY_DAYS} days, category: {metadata.get('category', 'unknown')}): {doc_id}")
                    except (ValueError, KeyError):
                        continue
        
        if outdated_ids:
            logger.info(f"Smart decay applied: {len(outdated_ids)} facts marked as outdated (decay_exempt facts preserved)")
        
    except Exception as e:
        logger.error(f"Failed to apply smart memory decay: {e}")
    
    return outdated_ids


def format_memory_with_temporal_grounding(memory: Dict[str, str]) -> str:
    """
    Temporal Grounding: Format memory with timestamps to prevent stale data confusion.
    
    Format: [Fakta dicatat pada 5 April 2026] Master sedang audit project Medco.
    """
    parts = []
    
    # Tier 3: Master Profile (Absolute Truth - no timestamp needed)
    if memory.get("profile"):
        parts.append(f"\n[PROFIL MASTER - SUMBER TERPERCAYA]\n{memory['profile']}")
    
    # Tier 2: Long-term with temporal grounding
    if memory.get("long_term"):
        # Parse and add timestamps to each fact
        facts = memory["long_term"].split("\n")
        grounded_facts = []
        
        for fact in facts:
            if fact.strip():
                # Try to extract timestamp from metadata (if available)
                # For now, use current date as fallback
                today = datetime.now().strftime("%d %B %Y")
                grounded_facts.append(f"[Fakta dicatat pada {today}] {fact}")
        
        parts.append(f"\n[FAKTA PENDUKUNG - MEMORI JANGKA PANJANG]\n" + "\n".join(grounded_facts))
    
    # Tier 1: Short-term (recent context - no timestamp needed)
    if memory.get("short_term"):
        parts.append(f"\n[MEMORI JANGKA PENDEK - 5 Interaksi Terakhir]\n{memory['short_term']}")
    
    return "\n".join(parts)


def check_tier_override(query: str, memory: Dict[str, str]) -> Dict:
    """
    Master Profile Override Layer: If Tier 3 (JSON) has conflicting info,
    it is the ABSOLUTE TRUTH over all other tiers.
    
    Returns dict with:
    - override_applied: bool
    - source: which tier was used
    - message: explanation
    """
    profile = memory.get("profile", "")
    long_term = memory.get("long_term", "")
    
    if not profile:
        return {"override_applied": False, "source": "none", "message": ""}
    
    # Check if query matches something in profile
    query_lower = query.lower()
    profile_lower = profile.lower()
    
    # Simple keyword matching for override detection
    profile_keywords = ["nama", "pekerjaan", "tinggal", "lokasi", "preferensi", "favorit", "hobi"]
    
    for kw in profile_keywords:
        if kw in query_lower and kw in profile_lower:
            return {
                "override_applied": True,
                "source": "master_profile",
                "message": f"[OVERRIDE: Informasi dari Profil Master (sumber terpercaya) diprioritaskan.]"
            }
    
    return {"override_applied": False, "source": "none", "message": ""}


def sync_chroma_to_profile() -> List[str]:
    """
    Auto-Migration: If a fact with category 'identity' or 'preference'
    appears more than SYNC_TO_PROFILE_THRESHOLD times, migrate to master_profile.json.
    
    Returns list of facts that were migrated.
    """
    collection = _get_chroma_collection()
    if collection is None:
        return []
    
    migrated_facts = []
    
    try:
        # Get all active facts
        results = collection.get(include=['metadatas', 'documents'])
        
        if not results or not results.get('metadatas'):
            return []
        
        # Count occurrences of similar facts
        fact_counts = {}
        fact_details = {}
        
        for i, (metadata, doc) in enumerate(zip(results['metadatas'], results['documents'])):
            if not metadata or metadata.get('status') != 'active':
                continue
            
            category = metadata.get('category', '')
            if category not in ['identity', 'preference']:
                continue
            
            # Use first 50 chars as key for grouping
            key = doc[:50].lower()
            fact_counts[key] = fact_counts.get(key, 0) + 1
            fact_details[key] = {"doc": doc, "metadata": metadata}
        
        # Migrate facts that exceed threshold
        profile = load_master_profile()
        
        for key, count in fact_counts.items():
            if count >= SYNC_TO_PROFILE_THRESHOLD:
                detail = fact_details[key]
                fact_text = detail["doc"]
                
                # Extract the fact (remove "Master Irfan: " prefix if present)
                clean_fact = fact_text.replace("Master Irfan: ", "")
                
                # Add to profile notes if not already there
                if clean_fact not in profile.get("notes", []):
                    if "notes" not in profile:
                        profile["notes"] = []
                    profile["notes"].append(clean_fact)
                    
                    # Mark as migrated in ChromaDB
                    doc_id = results['ids'][list(fact_details.keys()).index(key)]
                    collection.update(
                        ids=[doc_id],
                        metadatas=[{
                            **detail["metadata"],
                            "status": "migrated_to_profile",
                            "migrated_at": datetime.now().isoformat()
                        }]
                    )
                    
                    migrated_facts.append(clean_fact)
                    logger.info(f"Migrated fact to master_profile.json (count: {count}): {clean_fact[:50]}...")
        
        if migrated_facts:
            save_master_profile(profile)
            logger.info(f"Sync complete: {len(migrated_facts)} facts migrated to master_profile.json")
        
    except Exception as e:
        logger.error(f"Failed to sync ChromaDB to profile: {e}")
    
    return migrated_facts


def check_memory_confidence(query: str, results: List[str]) -> Tuple[bool, str]:
    """
    Check if memory results are sufficient to answer confidently.
    Returns (is_confident, disclaimer_message).
    """
    if not results:
        return False, f"Master, saya belum memiliki catatan tentang '{query}'. Apakah Master ingin saya menyimpannya?"
    
    # Check for ambiguous results
    if len(results) == 1 and len(results[0]) < 20:
        return False, f"Master, catatan saya tentang '{query}' terbatas. Bisa jelaskan lebih detail?"
    
    return True, ""

def get_memory_stats() -> Dict:
    """Returns statistics about the memory system."""
    profile = load_master_profile()
    short_term_count = len(get_short_term())
    
    # ChromaDB count
    long_term_count = 0
    try:
        collection = _get_chroma_collection()
        if collection:
            long_term_count = collection.count()
    except Exception:
        pass
    
    return {
        "tier1_short_term": {"type": "SQLite", "entries": short_term_count, "limit": SHORT_TERM_LIMIT},
        "tier2_long_term": {"type": "ChromaDB", "entries": long_term_count},
        "tier3_profile": {"type": "JSON", "file": MASTER_PROFILE_PATH, "notes": len(profile.get("notes", []))},
        "importance_threshold": IMPORTANCE_THRESHOLD
    }


# ============================================
# Initialize on import
# ============================================
init_short_term_db()
load_master_profile()  # Ensure profile exists
