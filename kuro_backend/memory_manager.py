"""
Kuro Cognitive Memory Engine - Tier-3 Architecture
====================================================
TIER 1: Short-Term Buffer (SQLite) - Last 20 interactions
TIER 2: Semantic Long-Term Memory (ChromaDB) - Embedded facts
TIER 3: Structured Knowledge Base (JSON) - Permanent master profile

Anti-Hallucination Protocol: If no memory found, ask instead of fabricating.
"""
import json
import logging
import os
import re
import sqlite3
import threading
from datetime import datetime
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

# Keywords that trigger memory storage
MEMORY_KEYWORDS = ["ingat", "simpan", "jadwal", "info", "spesifikasi", "catat", "profile", "preferensi"]

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
# Anti-Hallucination Protocol
# ============================================
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
