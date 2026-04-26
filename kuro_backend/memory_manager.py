"""
Kuro AI V6.0 Sovereign - Memory Manager [2026-04-17]
================================================================================
Kuro Cognitive Memory Engine V3.0 - Contextual RAG Architecture
TIER 1: Short-Term Buffer (SQLite) - Last 20 interactions
TIER 2: Semantic Long-Term Memory (ChromaDB) - Context-enriched embedded facts
TIER 3: Structured Knowledge Base (JSON) - Permanent master profile (ABSOLUTE TRUTH)

--- Header Doc ---
Purpose: Three-tier cognitive memory orchestration (short-term SQLite, semantic ChromaDB, master-profile JSON).
Caller: memory_coordinator, langgraph_core, core.py, services/core_service, dreaming_worker.
Dependencies: sqlite3, chromadb, google-genai (embeddings + summaries), embedding_cache, perpetual_memory.
Main Functions: add_interaction(), retrieve_context(), semantic_upsert_fact(), extract_facts(), cleanup_old_facts(), load_master_profile().
Side Effects: Writes to kuro_short_term.db, ChromaDB vector store, master_profile.json; Gemini embedding + summarization calls; background decay threads.

V3.0 CONTEXTUAL RAG:
- Contextual Ingestion: Gemini 3 generates global file context before chunking
- Context-Enriched Chunks: Each chunk prefixed with file-level context for better retrieval
- Query Expansion: Gemini 3 expands ambiguous queries using conversation context
- Resource Protection: Batch processing with RAM safeguards for 6GB systems

Anti-Hallucination Protocol V2.1:
- Semantic Upsert: Deduplication with similarity search + Gemini Flash classification
- Categorical Fact Tagging: identity/preference/goal/schedule/temporary
- Smart Decay: Respects decay_exempt for permanent facts
- Temporal Grounding: Inject timestamps into prompt to prevent stale data confusion
- Master Profile Override: Tier 3 is absolute truth over all other tiers
- Auto-Migration: Repeated facts auto-sync to master_profile.json

PHASE 2 Fixes [2026-04-05]:
- Context Ranking: Relevance threshold filtering for ChromaDB results
- Anti-VCT Bias: VCT data only returned for VCT-specific queries
"""
import json
import hashlib
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from kuro_backend.config import settings

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

# ============================================
# JSON Parsing Utilities
# ============================================
def extract_json_from_text(text: str) -> Optional[Dict]:
    """
    Robust JSON extraction from text that may contain markdown code blocks,
    extra whitespace, or non-JSON content.
    
    Handles:
    - ```json ... ``` markdown blocks
    - ``` ... ``` code blocks without language tag
    - Raw JSON with surrounding text
    - String responses that need to be parsed
    
    Returns dict if successful, None otherwise.
    """
    if not text or not isinstance(text, str):
        return None
    
    text = text.strip()
    
    # Step 1: Try to extract from markdown code block first
    json_block_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if json_block_match:
        text = json_block_match.group(1)
    
    # Step 2: Try to find JSON object in text
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    
    # Step 3: If text itself is a JSON string, try direct parse
    if text.startswith('{') and text.endswith('}'):
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    
    return None


# ============================================
# Configuration
# ============================================
BASE_DIR = settings.WORKING_DIR
SHORT_TERM_DB = os.path.join(BASE_DIR, "kuro_short_term.db")
LONG_TERM_DIR = os.path.join(BASE_DIR, "kuro_chromadb")
MASTER_PROFILE_PATH = os.path.join(BASE_DIR, "master_profile.json")

SHORT_TERM_LIMIT = 15  # Last 15 raw turns
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

CANONICAL_PERSONAS = [
    "consultant",
    "advisor",
    "chill",
    "tactical",
    "butler",
    "chancellor",
    "auditor",
]
PERSONA_ALIASES = {
    "support": "tactical",
    "adversarial_scholar": "advisor",
    "technical": "tactical",
    "casual": "chill",
    "qa": "auditor",
}

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
        return {"master": {"name": "Pantronux"}, "infrastructure": {}, "preferences": {}, "notes": []}

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
    lines.append(f"Nama Master: {profile.get('master', {}).get('name', 'Pantronux')}")
    
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

def get_active_persona() -> str:
    """Get the currently active persona."""
    profile = load_master_profile()
    raw = profile.get('preferences', {}).get('persona_mode', 'consultant')
    return normalize_persona(raw)


def normalize_persona(persona: str) -> str:
    """Normalize persona name to canonical enum."""
    raw = (persona or "").strip().lower()
    if raw in CANONICAL_PERSONAS:
        return raw
    if raw in PERSONA_ALIASES:
        return PERSONA_ALIASES[raw]
    return "consultant"

def set_active_persona(persona: str) -> Dict:
    """Set the active persona and save to master profile."""
    valid_personas = CANONICAL_PERSONAS + sorted(PERSONA_ALIASES.keys())
    incoming = (persona or "").strip().lower()
    if incoming not in valid_personas:
        return {"status": "error", "message": f"Invalid persona. Must be one of: {valid_personas}"}
    normalized = normalize_persona(incoming)
    
    profile = load_master_profile()
    if 'preferences' not in profile:
        profile['preferences'] = {}
    profile['preferences']['persona_mode'] = normalized
    save_master_profile(profile)
    logger.info(f"Active persona changed to: {normalized}")
    return {"status": "success", "persona": normalized}


def set_runtime_context_value(key: str, value: str) -> None:
    """Persist lightweight runtime context in master profile preferences."""
    profile = load_master_profile()
    preferences = profile.setdefault("preferences", {})
    runtime_context = preferences.setdefault("runtime_context", {})
    runtime_context[key] = value
    save_master_profile(profile)


def get_runtime_context_value(key: str, default: str = "") -> str:
    """Fetch runtime context value from master profile preferences."""
    profile = load_master_profile()
    return (
        profile.get("preferences", {})
        .get("runtime_context", {})
        .get(key, default)
    )

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
            persona_scope TEXT NOT NULL DEFAULT 'consultant',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("PRAGMA table_info(short_term)")
    columns = [row["name"] for row in cursor.fetchall()]
    if "persona_scope" not in columns:
        cursor.execute("ALTER TABLE short_term ADD COLUMN persona_scope TEXT NOT NULL DEFAULT 'consultant'")

    # Sliding-window summary cache (P2.1) — one row per persona. Keeps the
    # compressed summary of older turns keyed by the highest short_term.id
    # that was included, so we regenerate only when truly new turns arrive.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS short_term_summaries (
            persona_scope TEXT PRIMARY KEY,
            last_entry_id INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT '',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Persona-Aware Context Management (V5.5) — structured JSON summary
    # alongside the legacy plain-text fallback.
    cursor.execute("PRAGMA table_info(short_term_summaries)")
    summary_cols = [row["name"] for row in cursor.fetchall()]
    if "summary_json" not in summary_cols:
        cursor.execute(
            "ALTER TABLE short_term_summaries ADD COLUMN summary_json TEXT NOT NULL DEFAULT '{}'"
        )

    # Append-only durability ledger. Stores per-persona extraction records
    # (novelty_points, technical_specs, decisions, ...) so summarization can
    # NEVER cause data loss — even when the compressed summary is trimmed or
    # overwritten, these rows persist for PhD research audit.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS research_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            persona_scope TEXT NOT NULL,
            kind TEXT NOT NULL,
            content TEXT NOT NULL,
            source_entry_id INTEGER,
            schema_v INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_ledger_persona_kind "
        "ON research_ledger (persona_scope, kind)"
    )

    # Autonomous Memory Dreaming (V5.5) — advisory lease, cycle audit log,
    # and proactive notification dedup table.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dreaming_locks (
            name TEXT PRIMARY KEY,
            leased_by TEXT NOT NULL,
            lease_expires_at DATETIME NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dreaming_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at DATETIME NOT NULL,
            finished_at DATETIME,
            status TEXT NOT NULL,
            findings_count INTEGER NOT NULL DEFAULT 0,
            enriched_count INTEGER NOT NULL DEFAULT 0,
            notified_count INTEGER NOT NULL DEFAULT 0,
            error TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dream_notifications (
            fingerprint TEXT PRIMARY KEY,
            persona_scope TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Active Buffer / Session File Store (V7.0)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_file_store (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_file_store_session "
        "ON session_file_store (session_id)"
    )

    conn.commit()
    conn.close()
    logger.info("Short-term memory database initialized.")


def get_short_term_with_ids(persona_scope: str = None) -> List[Dict]:
    """Same as :func:`get_short_term` but includes the SQLite row id per entry.

    Needed for the sliding-window summary cache so we can key summaries by the
    highest id they cover.
    """
    scope = normalize_persona(persona_scope or get_active_persona())
    conn = _get_short_term_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, role, content, persona_scope, timestamp FROM short_term "
        "WHERE persona_scope = ? ORDER BY id DESC LIMIT ?",
        (scope, SHORT_TERM_LIMIT),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "persona_scope": r["persona_scope"],
            "timestamp": r["timestamp"],
        }
        for r in reversed(rows)
    ]


def get_short_term_summary(persona_scope: str) -> Optional[Dict]:
    """Return cached summary row ``(last_entry_id, summary)`` or ``None``."""
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_entry_id, summary FROM short_term_summaries WHERE persona_scope = ?",
            (persona_scope,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"last_entry_id": int(row["last_entry_id"]), "summary": str(row["summary"] or "")}


def upsert_short_term_summary(persona_scope: str, last_entry_id: int, summary: str) -> None:
    """Upsert the compressed-history cache for a persona scope."""
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO short_term_summaries (persona_scope, last_entry_id, summary) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(persona_scope) DO UPDATE SET "
            "last_entry_id=excluded.last_entry_id, summary=excluded.summary, "
            "updated_at=CURRENT_TIMESTAMP",
            (persona_scope, int(last_entry_id), summary),
        )
        conn.commit()
    finally:
        conn.close()


def get_short_term_summary_json(persona_scope: str) -> Optional[Dict]:
    """Return cached structured summary JSON for the persona, or ``None``.

    Falls back to parsing the legacy ``summary`` column into a minimal dict so
    callers can migrate without a flag day.
    """
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_entry_id, summary, summary_json FROM short_term_summaries "
            "WHERE persona_scope = ?",
            (persona_scope,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    last_id = int(row["last_entry_id"])
    raw_json = str(row["summary_json"] or "").strip()
    data: Dict = {}
    if raw_json and raw_json != "{}":
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            data = {}
    if not data and row["summary"]:
        data = {"topic": "", "decisions": [], "entities": [],
                "open_questions": [], "novelty_points": [],
                "technical_specs": [], "compliance_refs": [],
                "tone_markers": [], "_legacy_text": str(row["summary"] or "")}
    return {"last_entry_id": last_id, "summary_json": data}


def upsert_short_term_summary_json(
    persona_scope: str,
    last_entry_id: int,
    summary_json: Dict,
    *,
    fallback_text: str = "",
) -> None:
    """Upsert the structured JSON summary for a persona scope.

    Also stores ``fallback_text`` in the legacy ``summary`` column so older
    code paths keep working even before full migration.
    """
    blob = json.dumps(summary_json or {}, ensure_ascii=False)
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO short_term_summaries "
            "(persona_scope, last_entry_id, summary, summary_json) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(persona_scope) DO UPDATE SET "
            "last_entry_id=excluded.last_entry_id, "
            "summary=excluded.summary, "
            "summary_json=excluded.summary_json, "
            "updated_at=CURRENT_TIMESTAMP",
            (persona_scope, int(last_entry_id), fallback_text, blob),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Research Ledger (append-only) — PhD memory durability guarantee.
# ---------------------------------------------------------------------------

_LEDGER_KINDS: Tuple[str, ...] = (
    "novelty_point",
    "technical_spec",
    "decision",
    "open_question",
    "compliance_ref",
    "entity",
)


def append_research_ledger(
    persona_scope: str,
    kind: str,
    content: str,
    *,
    source_entry_id: Optional[int] = None,
    schema_v: int = 1,
) -> Optional[int]:
    """Append one research ledger row. Returns inserted row id or None on failure.

    Silently ignores empty content. Unknown ``kind`` values are accepted (we
    want extensibility) but logged so drift is visible.
    """
    content = (content or "").strip()
    if not content:
        return None
    if kind not in _LEDGER_KINDS:
        logger.debug("[LEDGER] unknown kind=%s persona=%s", kind, persona_scope)
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO research_ledger "
            "(persona_scope, kind, content, source_entry_id, schema_v) "
            "VALUES (?, ?, ?, ?, ?)",
            (persona_scope, kind, content, source_entry_id, int(schema_v)),
        )
        conn.commit()
        return int(cursor.lastrowid)
    except Exception as exc:
        logger.warning("[LEDGER] append failed persona=%s kind=%s: %s",
                       persona_scope, kind, exc)
        return None
    finally:
        conn.close()


def append_research_ledger_batch(
    persona_scope: str,
    records: List[Dict],
    *,
    source_entry_id: Optional[int] = None,
) -> int:
    """Append multiple ledger rows in a single transaction.

    Each record dict must have ``kind`` and ``content`` keys. Returns the count
    of rows actually inserted (non-empty content only).
    """
    rows: List[Tuple] = []
    for rec in records or []:
        content = str(rec.get("content") or "").strip()
        if not content:
            continue
        kind = str(rec.get("kind") or "").strip() or "decision"
        rows.append((persona_scope, kind, content,
                     rec.get("source_entry_id") or source_entry_id, 1))
    if not rows:
        return 0
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.executemany(
            "INSERT INTO research_ledger "
            "(persona_scope, kind, content, source_entry_id, schema_v) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        return len(rows)
    except Exception as exc:
        logger.warning("[LEDGER] batch append failed persona=%s count=%d: %s",
                       persona_scope, len(rows), exc)
        return 0
    finally:
        conn.close()


def query_research_ledger(
    persona_scope: str,
    *,
    kinds: Optional[List[str]] = None,
    limit: int = 50,
) -> List[Dict]:
    """Return most recent ledger rows for a persona, newest first."""
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        if kinds:
            placeholders = ",".join("?" * len(kinds))
            cursor.execute(
                f"SELECT id, kind, content, source_entry_id, created_at "
                f"FROM research_ledger WHERE persona_scope = ? AND kind IN ({placeholders}) "
                f"ORDER BY id DESC LIMIT ?",
                (persona_scope, *kinds, int(limit)),
            )
        else:
            cursor.execute(
                "SELECT id, kind, content, source_entry_id, created_at "
                "FROM research_ledger WHERE persona_scope = ? ORDER BY id DESC LIMIT ?",
                (persona_scope, int(limit)),
            )
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [
        {
            "id": int(r["id"]),
            "kind": str(r["kind"]),
            "content": str(r["content"]),
            "source_entry_id": r["source_entry_id"],
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


def query_research_ledger_since(
    cutoff_iso: str,
    *,
    limit: int = 500,
) -> List[Dict]:
    """Return ledger rows created since ``cutoff_iso`` across all personas."""
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, persona_scope, kind, content, source_entry_id, created_at "
            "FROM research_ledger WHERE created_at >= ? "
            "ORDER BY id DESC LIMIT ?",
            (cutoff_iso, int(limit)),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [
        {
            "id": int(r["id"]),
            "persona_scope": str(r["persona_scope"]),
            "kind": str(r["kind"]),
            "content": str(r["content"]),
            "source_entry_id": r["source_entry_id"],
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


def query_short_term_summaries_recent(limit: int = 50) -> List[Dict]:
    """Return the most recently updated short_term_summaries rows.

    We can't filter by a ``created_at`` column (there isn't one), but
    ``updated_at`` reflects when the summarizer last wrote. Caller filters
    further by parsing ``updated_at``.
    """
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT persona_scope, last_entry_id, summary, summary_json, updated_at "
            "FROM short_term_summaries ORDER BY updated_at DESC LIMIT ?",
            (int(limit),),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [
        {
            "persona_scope": str(r["persona_scope"]),
            "last_entry_id": int(r["last_entry_id"]),
            "summary": str(r["summary"] or ""),
            "summary_json": str(r["summary_json"] or "{}"),
            "updated_at": str(r["updated_at"]),
        }
        for r in rows
    ]


def query_short_term_latest_timestamp() -> Optional[str]:
    """Return ISO timestamp of the most recent short_term row, or None."""
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timestamp FROM short_term ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return str(row["timestamp"])

# ---------------------------------------------------------------------------
# Session File Store (Active Buffer V7.0)
# ---------------------------------------------------------------------------
def upsert_session_file(session_id: str, filename: str, content: str) -> None:
    """Upsert file content for a specific session."""
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        # Delete existing file with the same name in the same session
        cursor.execute(
            "DELETE FROM session_file_store WHERE session_id = ? AND filename = ?",
            (session_id, filename)
        )
        cursor.execute(
            "INSERT INTO session_file_store (session_id, filename, content) VALUES (?, ?, ?)",
            (session_id, filename, content)
        )
        conn.commit()
    finally:
        conn.close()

def get_session_files(session_id: str) -> List[Dict[str, str]]:
    """Retrieve all files associated with a specific session."""
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT filename, content FROM session_file_store WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,)
        )
        rows = cursor.fetchall()
        return [{"filename": str(row["filename"]), "content": str(row["content"])} for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Autonomous Dreaming — advisory lease, cycle audit, notification dedup
# ---------------------------------------------------------------------------

def acquire_dreaming_lease(name: str, leased_by: str, ttl_seconds: int) -> bool:
    """Try to acquire an advisory lease on ``name`` with ``ttl_seconds`` TTL.

    Returns ``True`` when acquired (row inserted or previous lease expired),
    ``False`` when another holder still owns the active lease.

    Implementation uses the stale-or-empty row as precondition so we never
    steal a live lease.
    """
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        now = datetime.now()
        expires = now + timedelta(seconds=max(60, int(ttl_seconds)))
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT leased_by, lease_expires_at FROM dreaming_locks WHERE name = ?",
            (name,),
        )
        row = cursor.fetchone()
        if row is not None:
            try:
                held_until = datetime.fromisoformat(str(row["lease_expires_at"]))
            except ValueError:
                held_until = now - timedelta(seconds=1)
            if held_until > now:
                conn.rollback()
                return False
        cursor.execute(
            "INSERT INTO dreaming_locks (name, leased_by, lease_expires_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "leased_by=excluded.leased_by, "
            "lease_expires_at=excluded.lease_expires_at",
            (name, leased_by, expires.isoformat(timespec="seconds")),
        )
        conn.commit()
        return True
    except Exception as exc:
        logger.warning("[DREAMING_LEASE] acquire failed name=%s: %s", name, exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def release_dreaming_lease(name: str, leased_by: str) -> None:
    """Release the lease only if we still own it (safe no-op otherwise)."""
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM dreaming_locks WHERE name = ? AND leased_by = ?",
            (name, leased_by),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("[DREAMING_LEASE] release failed name=%s: %s", name, exc)
    finally:
        conn.close()


def insert_dreaming_cycle(status: str = "running") -> int:
    """Insert a new dreaming cycle audit row. Returns the row id."""
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO dreaming_cycles (started_at, status) VALUES (?, ?)",
            (datetime.now().isoformat(timespec="seconds"), status),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def update_dreaming_cycle(
    cycle_id: int,
    *,
    status: str,
    findings_count: int = 0,
    enriched_count: int = 0,
    notified_count: int = 0,
    error: Optional[str] = None,
) -> None:
    """Update a dreaming cycle audit row with final counts + status."""
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE dreaming_cycles SET "
            "finished_at = ?, status = ?, findings_count = ?, "
            "enriched_count = ?, notified_count = ?, error = ? "
            "WHERE id = ?",
            (
                datetime.now().isoformat(timespec="seconds"),
                status,
                int(findings_count),
                int(enriched_count),
                int(notified_count),
                (error or None),
                int(cycle_id),
            ),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("[DREAMING_CYCLE] update failed id=%s: %s", cycle_id, exc)
    finally:
        conn.close()


def dream_notification_seen(fingerprint: str) -> bool:
    """Return True if this notification fingerprint was already sent."""
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM dream_notifications WHERE fingerprint = ? LIMIT 1",
            (fingerprint,),
        )
        row = cursor.fetchone()
        return row is not None
    finally:
        conn.close()


def mark_dream_notification(
    fingerprint: str, persona_scope: str, kind: str,
) -> None:
    """Record that a fingerprint was successfully notified."""
    conn = _get_short_term_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO dream_notifications "
            "(fingerprint, persona_scope, kind) VALUES (?, ?, ?)",
            (fingerprint, persona_scope, kind),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("[DREAM_NOTIFY] mark failed fp=%s: %s", fingerprint, exc)
    finally:
        conn.close()

def add_short_term(role: str, content: str, persona_scope: str = None):
    """Add interaction to short-term buffer."""
    scope = normalize_persona(persona_scope or get_active_persona())
    conn = _get_short_term_conn()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO short_term (role, content, persona_scope) VALUES (?, ?, ?)",
        (role, content, scope),
    )
    
    # Enforce limit - delete oldest if over limit
    cursor.execute(
        """
        DELETE FROM short_term
        WHERE persona_scope = ?
          AND id NOT IN (
              SELECT id FROM short_term WHERE persona_scope = ? ORDER BY id DESC LIMIT ?
          )
        """,
        (scope, scope, SHORT_TERM_LIMIT),
    )
    
    conn.commit()
    conn.close()

def get_short_term(persona_scope: str = None) -> List[Dict]:
    """Get recent short-term memory."""
    scope = normalize_persona(persona_scope or get_active_persona())
    conn = _get_short_term_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM short_term WHERE persona_scope = ? ORDER BY id DESC LIMIT ?",
        (scope, SHORT_TERM_LIMIT),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "role": r["role"],
            "content": r["content"],
            "persona_scope": r["persona_scope"],
            "timestamp": r["timestamp"],
        }
        for r in reversed(rows)
    ]

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

# Legacy L2 distance cap (used as default MEMORY_MAX_L2_DISTANCE)
RELEVANCE_DISTANCE_THRESHOLD = 0.5  # Lower distance = more relevant (0 = perfect match)

# Cosine collections: min similarity in [0,1] (we use sim = 1 - d/2 on Chroma cosine distance)
MEMORY_INJECTION_MIN_SIMILARITY = float(os.getenv("KURO_MEMORY_MIN_SIMILARITY", "0.7"))
# L2 (default long-term): Chroma distances are often >1; do not use 1/(1+d)>=0.7 (that implies d<=0.43).
# Keep a direct distance ceiling aligned with legacy RELEVANCE_DISTANCE_THRESHOLD unless overridden.
MEMORY_MAX_L2_DISTANCE = float(os.getenv("KURO_MEMORY_MAX_L2_DISTANCE", str(RELEVANCE_DISTANCE_THRESHOLD)))


def _collection_vector_space(collection) -> str:
    try:
        meta = getattr(collection, "metadata", None) or {}
        return str(meta.get("hnsw:space", "l2")).lower()
    except Exception:
        return "l2"


def _memory_relevance_similarity(distance: float, space: str) -> float:
    """Map Chroma distance to [0,1] similarity (for logging / cosine gating only)."""
    space = (space or "l2").lower()
    d = float(distance)
    if space == "cosine":
        return max(0.0, 1.0 - (d / 2.0))
    # L2: monotonic score for debug only — gating uses MEMORY_MAX_L2_DISTANCE
    return 1.0 / (1.0 + max(0.0, d))


def memory_similarity_passes(distance: float, space: str) -> bool:
    space = (space or "l2").lower()
    d = float(distance)
    if space == "cosine":
        return _memory_relevance_similarity(d, "cosine") >= MEMORY_INJECTION_MIN_SIMILARITY
    return d <= MEMORY_MAX_L2_DISTANCE

def search_long_term(query: str, top_k: int = 5) -> List[str]:
    """Search ChromaDB for relevant facts with context ranking.
    
    PHASE 2 FIX:
    - Only returns facts with relevance score above threshold
    - Anti-VCT bias: VCT data only returned if query contains VCT keywords
    """
    collection = _get_chroma_collection()
    if collection is None:
        return []
    
    try:
        space = _collection_vector_space(collection)
        results = collection.query(query_texts=[query], n_results=top_k, include=['documents', 'distances'])
        documents = results.get('documents', [[]])[0]
        distances = results.get('distances', [[]])[0]
        
        # PHASE 2: Context Ranking - filter by similarity floor for LLM injection
        relevant_facts = []
        for doc, distance in zip(documents, distances):
            if memory_similarity_passes(distance, space):
                relevant_facts.append(doc)
            else:
                logger.debug(
                    "Filtered low-similarity fact (sim=%.3f space=%s): %s...",
                    _memory_relevance_similarity(distance, space),
                    space,
                    doc[:50],
                )
        
        # PHASE 2: Anti-VCT Bias - only return VCT data if query is VCT-related
        vct_keywords = ['vct', 'valorant', 'tournament', 'competition ruleset', 'vct26']
        query_lower = query.lower()
        is_vct_query = any(kw in query_lower for kw in vct_keywords)
        
        if not is_vct_query:
            # Filter out VCT-related facts unless specifically asked
            vct_filtered = []
            for fact in relevant_facts:
                fact_lower = fact.lower()
                if any(kw in fact_lower for kw in vct_keywords):
                    logger.debug(f"Filtered out VCT fact (not VCT query): {fact[:50]}...")
                else:
                    vct_filtered.append(fact)
            relevant_facts = vct_filtered

        if not relevant_facts and documents and distances:
            logger.debug(
                "Memory search: all %d candidates rejected (space=%s cosine_min_sim=%s l2_max_d=%s sample_d=%.4f)",
                len(documents),
                space,
                MEMORY_INJECTION_MIN_SIMILARITY,
                MEMORY_MAX_L2_DISTANCE,
                float(distances[0]),
            )

        logger.debug(
            "Memory search: %s results -> %s relevant (space=%s cosine_min_sim=%s l2_max_d=%s)",
            len(documents),
            len(relevant_facts),
            space,
            MEMORY_INJECTION_MIN_SIMILARITY,
            MEMORY_MAX_L2_DISTANCE,
        )
        return relevant_facts
        
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
def query_memory(
    current_message: str,
    recent_messages: List[Dict] = None,
    persona_scope: str = None,
    include_compliance: bool = False,
) -> Dict[str, str]:
    """
    Pre-process memory before AI response.
    
    KURO V7.0: Preserve only short-term raw context + master profile.
    Long-term semantic context is handled by Mem0 in memory_coordinator.
    """
    # Tier 1: Short-term
    scope = normalize_persona(persona_scope or get_active_persona())
    short_term_entries = get_short_term(persona_scope=scope)
    short_term_text = ""
    if short_term_entries:
        summaries = []
        for entry in short_term_entries[-15:]:
            role_label = "User" if entry["role"] == "user" else "Kuro"
            summaries.append(f"{role_label}: {entry['content'][:800]}")
        short_term_text = "\n".join(summaries)

    # Tier 3: Master profile
    profile_text = get_master_profile_formatted()

    return {
        "short_term": short_term_text,
        "long_term": "",
        "profile": profile_text,
        "compliance": "",
    }

def format_memory_injection(memory: Dict[str, str]) -> str:
    """Format memory sections for prompt injection."""
    parts = []
    
    if memory["profile"]:
        parts.append(f"\n[PROFIL MASTER]\n{memory['profile']}")
    
    if memory["short_term"]:
        parts.append(f"\n[MEMORI JANGKA PENDEK - 15 Turn Terakhir]\n{memory['short_term']}")
    
    if memory["long_term"]:
        parts.append(f"\n[FAKTA PENDUKUNG - Memori Jangka Panjang]\n{memory['long_term']}")
    
    # V3.1: Compliance Knowledge Base (Golden Memory Tier)
    
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


def summarize_conversation_to_chroma(persona_scope: str = None):
    """
    Conversation Summarization: When short-term buffer is full,
    summarize the conversation and store to ChromaDB for long-term retention.
    """
    scope = normalize_persona(persona_scope or get_active_persona())
    entries = get_short_term(persona_scope=scope)
    
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
            "source": "auto_summary",
            "persona_scope": scope,
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
                        add_long_term(f"Pantronux: {fact}", metadata={
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
        from kuro_backend.config import CLASSIFIER_MODEL
        
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        prompt = f"""Klasifikasikan fakta berikut tentang Pantronux ke dalam kategori yang tepat.

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
            model=CLASSIFIER_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1)
        )
        
        # SAFETY CHECK: Check prompt_feedback before accessing response.text
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
            logger.warning(f"[CLASSIFIER] Content blocked: {getattr(response.prompt_feedback, 'block_reason', 'UNKNOWN')}")
            return {"fact": fact, "category": "temporary", "decay_exempt": False}
        
        # PHASE 2: Error handling for API responses - safe text access
        try:
            resp_text = response.text if response.text else ""
        except Exception as text_err:
            if "WARNING" in str(text_err) or "Safety" in str(text_err) or "blocked" in str(text_err).lower():
                logger.warning(f"[CLASSIFIER] response.text blocked: {text_err}")
                return {"fact": fact, "category": "temporary", "decay_exempt": False}
            raise text_err
        
        if not resp_text or not resp_text.strip():
            logger.error("Critical: Classifier Model Failed - Empty response. Falling back to safe mode.")
            return {"fact": fact, "category": "temporary", "decay_exempt": False}
        
        # Use robust JSON extraction helper
        result = extract_json_from_text(resp_text)
        if result and "category" in result and "decay_exempt" in result:
            logger.info(f"[CLASSIFIER] {fact[:50]}... -> {result.get('category')} (decay_exempt={result.get('decay_exempt')})")
            return result
        
        # Fallback if parsing fails
        logger.warning(f"[CLASSIFIER] JSON extraction failed, using fallback for: {fact[:50]}...")
        return {"fact": fact, "category": "temporary", "decay_exempt": False}
        
    except Exception as e:
        logger.error(f"Critical: Classifier Model Failed - {e}. Falling back to safe mode.")
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
                
                # Extract the fact (remove "Pantronux: " prefix if present)
                clean_fact = fact_text.replace("Pantronux: ", "")
                
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
# V3.0 CONTEXTUAL RAG - GEMINI 3 ENGINE
# ============================================

# Configuration for Contextual RAG
CONTEXT_MAX_CHARS = 100000  # Max characters to send for context generation (100k)
CHUNK_SIZE = 1500  # Characters per chunk
CHUNK_OVERLAP = 200  # Overlap between chunks for context continuity
MAX_FILES_PER_BATCH = 5  # Process max 5 files at once to avoid OOM
BATCH_DELAY_SECONDS = 2  # Delay between file processing

def generate_file_context(text: str, filename: str) -> str:
    """
    V3.0 CONTEXTUAL INGESTION - Step A (Global Context):
    Use Gemini 3 Flash to generate a 1-2 sentence dense description of the file.
    
    This context will be prepended to every chunk for better retrieval accuracy.
    
    Args:
        text: Full file text (or first 100k chars)
        filename: Name of the file for context
    
    Returns:
        A 1-2 sentence context string describing the file content.
    """
    try:
        from google import genai
        from google.genai import types
        from kuro_backend.config import PRIMARY_MODEL
        
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        # Truncate text if too long (resource protection)
        truncated_text = text[:CONTEXT_MAX_CHARS]
        char_count = len(truncated_text)
        
        prompt = f"""Analyze the following document content and generate a concise, information-dense 1-2 sentence description.

File: {filename}
Content length: {char_count} characters

Your description should capture:
- What type of document is this? (policy, technical spec, log, code, etc.)
- What is the main subject/topic?
- Any key entities, organizations, or time periods mentioned?
- What domain does this belong to? (security, IT infrastructure, compliance, etc.)

Content (first {char_count} chars):
---
{truncated_text[:5000]}
---

Respond with ONLY the 1-2 sentence description, nothing else. Example format:
"Ini adalah dokumen Kebijakan Keamanan Informasi PT Medco tahun 2026 yang fokus pada kontrol akses fisik dan logis sesuai ISO 27001:2022 Annex A.5 dan A.8."
"""
        
        response = client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=200
            )
        )
        
        # SAFETY CHECK
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
            logger.warning(f"[FILE_CONTEXT] Content blocked: {getattr(response.prompt_feedback, 'block_reason', 'UNKNOWN')}")
            return f"Dokumen: {filename} (konteks diblokir filter)"
        
        try:
            context = response.text.strip() if response.text else f"Dokumen: {filename}"
        except Exception as text_err:
            if "WARNING" in str(text_err) or "Safety" in str(text_err) or "blocked" in str(text_err).lower():
                logger.warning(f"[FILE_CONTEXT] response.text blocked: {text_err}")
                return f"Dokumen: {filename} (konteks diblokir filter)"
            raise text_err
        
        # Validate context length (should be 1-2 sentences)
        if len(context) > 300:
            context = context[:300] + "..."
        
        logger.info(f"[CONTEXT_GENERATED] for file: {filename} - {context[:80]}...")
        return context
        
    except Exception as e:
        logger.error(f"Failed to generate file context for {filename}: {e}")
        return f"Dokumen: {filename} (konteks gagal dibuat)"


def chunk_text_with_context(text: str, file_context: str, filename: str) -> List[Dict]:
    """
    V3.0 CONTEXTUAL INGESTION - Step B (Context Injection):
    Chunk text and prepend the global context to each chunk.
    
    Format: [FILE_CONTEXT: {deskripsi}] | [CHUNK_CONTENT: {isi_asli_chunk}]
    
    Args:
        text: Full file text
        file_context: Generated context from generate_file_context()
        filename: Name of the file
    
    Returns:
        List of dicts with 'id', 'content', 'metadata'
    """
    chunks = []
    
    # Split text into chunks with overlap
    start = 0
    chunk_index = 0
    
    while start < len(text):
        end = start + CHUNK_SIZE
        
        # Get chunk content
        chunk_content = text[start:end]
        
        # Skip empty chunks
        if not chunk_content.strip():
            start = end
            continue
        
        # Create enriched chunk with context
        enriched_content = f"[FILE_CONTEXT: {file_context}] | [CHUNK_CONTENT: {chunk_content}]"
        
        # Calculate chunk metadata
        chunk_metadata = {
            "source_file": filename,
            "chunk_index": chunk_index,
            "char_start": start,
            "char_end": min(end, len(text)),
            "timestamp": datetime.now().isoformat(),
            "type": "contextual_chunk",
            "importance": compute_importance_score(chunk_content)
        }
        
        chunks.append({
            "id": f"{filename}_chunk_{chunk_index}",
            "content": enriched_content,
            "metadata": chunk_metadata
        })
        
        chunk_index += 1
        start = end - CHUNK_OVERLAP  # Overlap for context continuity
    
    logger.info(f"Chunked {filename}: {chunk_index} chunks created (context: {file_context[:60]}...)")
    return chunks


def ingest_file_contextual(text: str, filename: str, metadata: Dict = None) -> Dict:
    """
    V3.0 CONTEXTUAL INGESTION - Main function:
    1. Generate global context with Gemini 3
    2. Chunk text with context injection
    3. Upsert enriched chunks to ChromaDB
    
    Args:
        text: Full file text content
        filename: Name of the file
        metadata: Additional metadata to attach
    
    Returns:
        Dict with ingestion results
    """
    collection = _get_chroma_collection()
    if collection is None:
        return {"success": False, "reason": "ChromaDB unavailable"}
    
    try:
        # Step A: Generate global context
        file_context = generate_file_context(text, filename)
        
        # Step B: Chunk with context injection
        chunks = chunk_text_with_context(text, file_context, filename)
        
        if not chunks:
            return {"success": False, "reason": "No chunks created"}
        
        # Step C: Upsert to ChromaDB
        ids = [chunk["id"] for chunk in chunks]
        documents = [chunk["content"] for chunk in chunks]
        metadatas = []
        
        for chunk in chunks:
            chunk_meta = chunk["metadata"].copy()
            chunk_meta["file_context"] = file_context[:200]  # Truncate for metadata
            if metadata:
                chunk_meta.update({k: v for k, v in metadata.items() if k not in chunk_meta})
            metadatas.append(chunk_meta)
        
        # Delete existing chunks for this file (re-index support)
        try:
            existing = collection.get(where={"source_file": filename})
            if existing and existing.get("ids"):
                collection.delete(ids=existing["ids"])
                logger.info(f"Deleted {len(existing['ids'])} existing chunks for {filename}")
        except Exception as e:
            logger.debug(f"No existing chunks to delete for {filename}: {e}")
        
        # Batch insert with RAM protection (max 100 chunks per batch)
        batch_size = 100
        total_inserted = 0
        
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i+batch_size]
            batch_docs = documents[i:i+batch_size]
            batch_meta = metadatas[i:i+batch_size]
            
            collection.add(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_meta
            )
            total_inserted += len(batch_ids)
            
            # Log progress for large files
            if len(ids) > batch_size:
                logger.info(f"Inserted batch {i//batch_size + 1}: {len(batch_ids)} chunks ({total_inserted}/{len(ids)})")
        
        logger.info(f"[CONTEXTUAL_INGEST] Complete: {filename} -> {total_inserted} chunks with context")
        
        return {
            "success": True,
            "filename": filename,
            "chunks_created": total_inserted,
            "file_context": file_context,
            "action": "contextual_ingest"
        }
        
    except Exception as e:
        logger.error(f"Failed to ingest file {filename} contextually: {e}")
        return {"success": False, "reason": str(e)}


def reindex_all_files(file_texts: Dict[str, str]) -> Dict:
    """
    V3.0 RE-INDEXING TRIGGER:
    Clear old ChromaDB collection and re-index all files with contextual RAG.
    
    This is a "mass cleanup" to ensure Kuro's memory isn't contaminated
    with old context-less data.
    
    Args:
        file_texts: Dict mapping filename -> text content
    
    Returns:
        Dict with re-indexing results
    """
    collection = _get_chroma_collection()
    if collection is None:
        return {"success": False, "reason": "ChromaDB unavailable"}
    
    results = {
        "success": True,
        "files_processed": 0,
        "total_chunks": 0,
        "errors": [],
        "contexts": {}
    }
    
    try:
        # Step 1: Clear old collection
        old_count = collection.count()
        logger.info(f"[REINDEX] Clearing {old_count} existing entries from ChromaDB...")
        
        # Delete all entries
        try:
            all_entries = collection.get()
            if all_entries and all_entries.get("ids"):
                collection.delete(ids=all_entries["ids"])
                logger.info(f"[REINDEX] Deleted {len(all_entries['ids'])} old entries")
        except Exception as e:
            logger.warning(f"[REINDEX] Could not delete all entries: {e}")
        
        # Step 2: Process files in batches (resource protection)
        file_list = list(file_texts.items())
        batch_count = 0
        
        for i in range(0, len(file_list), MAX_FILES_PER_BATCH):
            batch = file_list[i:i+MAX_FILES_PER_BATCH]
            batch_count += 1
            
            logger.info(f"[REINDEX] Processing batch {batch_count}: {len(batch)} files")
            
            for filename, text in batch:
                try:
                    result = ingest_file_contextual(text, filename)
                    
                    if result["success"]:
                        results["files_processed"] += 1
                        results["total_chunks"] += result["chunks_created"]
                        results["contexts"][filename] = result["file_context"]
                        logger.info(f"[REINDEX] ✓ {filename}: {result['chunks_created']} chunks")
                    else:
                        results["errors"].append({"file": filename, "error": result["reason"]})
                        logger.error(f"[REINDEX] ✗ {filename}: {result['reason']}")
                    
                except Exception as e:
                    results["errors"].append({"file": filename, "error": str(e)})
                    logger.error(f"[REINDEX] ✗ {filename}: {e}")
            
            # Delay between batches (RAM protection)
            if i + MAX_FILES_PER_BATCH < len(file_list):
                logger.info(f"[REINDEX] Waiting {BATCH_DELAY_SECONDS}s before next batch (RAM protection)...")
                time.sleep(BATCH_DELAY_SECONDS)
        
        logger.info(f"[REINDEX] Complete: {results['files_processed']} files, {results['total_chunks']} chunks, {len(results['errors'])} errors")
        
    except Exception as e:
        results["success"] = False
        results["errors"].append({"file": "reindex_process", "error": str(e)})
        logger.error(f"[REINDEX] Failed: {e}")
    
    return results


# ---------------------------------------------------------------------------
# Query-expansion cache (P1.3)
# ---------------------------------------------------------------------------
# Purpose: the ambiguous-query LLM expansion call adds 300-600ms to the hot
# path. Most follow-up turns repeat very similar queries within a short window,
# so a tiny TTL+LRU cache eliminates the call on repeats without changing
# cache-miss behavior.
_EXPAND_QUERY_CACHE: Dict[str, tuple[float, str]] = {}
_EXPAND_QUERY_CACHE_LOCK = threading.Lock()
_EXPAND_QUERY_CACHE_MAX = 256
_EXPAND_QUERY_CACHE_TTL_S = 60.0


def _expand_query_cache_key(query: str, recent_messages: List[Dict] | None) -> str:
    # Fingerprint on the last 3 messages (enough to determine anaphora context)
    # plus the normalized query. Avoids unbounded cache explosion and keeps the
    # cache behaviorally equivalent to a full recompute.
    tail = (recent_messages or [])[-3:]
    tail_blob = "\n".join(f"{m.get('role','')}:{(m.get('content','') or '')[:120]}" for m in tail)
    blob = f"{query.strip().lower()}\n---\n{tail_blob}"
    return hashlib.sha1(blob.encode("utf-8", errors="replace")).hexdigest()


def _expand_query_cache_get(key: str) -> Optional[str]:
    now = time.monotonic()
    with _EXPAND_QUERY_CACHE_LOCK:
        entry = _EXPAND_QUERY_CACHE.get(key)
        if entry is None:
            return None
        ts, value = entry
        if now - ts > _EXPAND_QUERY_CACHE_TTL_S:
            _EXPAND_QUERY_CACHE.pop(key, None)
            return None
        return value


def _expand_query_cache_put(key: str, value: str) -> None:
    now = time.monotonic()
    with _EXPAND_QUERY_CACHE_LOCK:
        if len(_EXPAND_QUERY_CACHE) >= _EXPAND_QUERY_CACHE_MAX:
            # Evict oldest entry (cheap since cache is small).
            oldest = min(_EXPAND_QUERY_CACHE.items(), key=lambda kv: kv[1][0])[0]
            _EXPAND_QUERY_CACHE.pop(oldest, None)
        _EXPAND_QUERY_CACHE[key] = (now, value)


def expand_query(query: str, recent_messages: List[Dict] = None) -> str:
    """
    V3.0 INTELLIGENT RETRIEVAL - Query Expansion:
    Use Gemini 3 to expand ambiguous queries using recent conversation context.
    
    If Master asks "ini maksudnya?" (what does this mean?), Gemini guesses the subject
    based on the last 3 chat messages before searching ChromaDB.
    
    Args:
        query: The user's query
        recent_messages: List of recent chat messages for context
    
    Returns:
        Expanded query string optimized for semantic search
    """
    if not recent_messages or len(recent_messages) < 2:
        return query  # No context to expand with
    
    # Check if query is ambiguous (short or pronoun-heavy)
    ambiguous_indicators = ["ini", "itu", "dia", "mereka", "tersebut", "maksudnya", "apa itu", "bagaimana"]
    query_lower = query.lower()
    
    is_ambiguous = (
        len(query.split()) <= 4 or  # Short query
        any(indicator in query_lower for indicator in ambiguous_indicators)
    )
    
    if not is_ambiguous:
        return query  # Query is specific enough

    cache_key = _expand_query_cache_key(query, recent_messages)
    cached = _expand_query_cache_get(cache_key)
    if cached is not None:
        logger.debug("[QUERY_EXPANSION] cache hit key=%s", cache_key[:8])
        return cached

    try:
        from google import genai
        from google.genai import types
        from kuro_backend.config import PRIMARY_MODEL
        
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        # Build conversation context
        context_msgs = []
        for msg in recent_messages[-6:]:  # Last 6 messages (3 exchanges)
            role = "User" if msg.get("role") == "user" else "Kuro"
            content = msg.get("content", "")[:200]  # Truncate
            context_msgs.append(f"{role}: {content}")
        
        conversation_context = "\n".join(context_msgs)
        
        prompt = f"""Based on the recent conversation, expand the user's ambiguous query into a clear, specific search query.

Recent conversation:
{conversation_context}

User's query: "{query}"

Your task:
1. Identify what "ini", "itu", "dia", etc. refers to based on conversation context
2. Create a clear, specific search query that captures the user's intent
3. Include relevant keywords from the conversation

Respond with ONLY the expanded query, nothing else.

Example:
- If user says "ini maksudnya?" and conversation was about ISO 27001 access control
- Respond: "ISO 27001 access control policy requirements and implementation details"
"""
        
        response = client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=64,
            )
        )
        
        # SAFETY CHECK
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
            logger.warning(f"[QUERY_EXPANSION] Content blocked: {getattr(response.prompt_feedback, 'block_reason', 'UNKNOWN')}")
            return query  # Fallback to original query
        
        try:
            expanded = response.text.strip() if response.text else query
        except Exception as text_err:
            error_str = str(text_err).lower()
            if "WARNING" in str(text_err) or "Safety" in str(text_err) or "blocked" in error_str:
                logger.warning(f"[QUERY_EXPANSION] response.text blocked: {text_err}")
                return query
            # FIX: Any error during text extraction falls back to original query
            logger.warning(f"[QUERY_EXPANSION] Failed to extract response text: {text_err}")
            return query
        
        # Validate expanded query - ensure it's a valid string
        if not isinstance(expanded, str):
            logger.warning(f"[QUERY_EXPANSION] Expanded query is not a string: {type(expanded)}")
            return query
        
        # Cap and validate length (Chroma / embedders reject overly long query strings)
        QUERY_EXPANSION_MAX = 150
        expanded = expanded.strip()
        if len(expanded) > QUERY_EXPANSION_MAX:
            expanded = expanded[:QUERY_EXPANSION_MAX].rstrip()
        if len(expanded) < 5:
            logger.warning(f"[QUERY_EXPANSION] Invalid length ({len(expanded)} chars), using original query")
            return query

        logger.info(f"[QUERY_EXPANSION] Original: '{query}' -> Expanded: '{expanded}'")
        _expand_query_cache_put(cache_key, expanded)
        return expanded
        
    except Exception as e:
        logger.error(f"Query expansion failed: {e}")
        return query  # Fallback to original query


def search_long_term_contextual(query: str, top_k: int = 5, recent_messages: List[Dict] = None) -> List[str]:
    """
    V3.0 ENHANCED SEARCH:
    Combines query expansion with contextual retrieval.
    
    Args:
        query: User's query
        top_k: Number of results to return
        recent_messages: Recent chat messages for query expansion
    
    Returns:
        List of relevant document strings
    """
    collection = _get_chroma_collection()
    if collection is None:
        return []
    
    try:
        # Step 1: Expand query if ambiguous
        expanded_query = expand_query(query, recent_messages)
        
        space = _collection_vector_space(collection)
        # Step 2: Search with expanded query
        results = collection.query(
            query_texts=[expanded_query],
            n_results=top_k * 2,  # Get more results for filtering
            include=['documents', 'distances', 'metadatas']
        )
        
        documents = results.get('documents', [[]])[0]
        distances = results.get('distances', [[]])[0]
        metadatas = results.get('metadatas', [[]])[0]
        
        # Step 3: Filter by similarity floor (query_memory / LLM injection)
        relevant_facts = []
        for doc, distance, metadata in zip(documents, distances, metadatas):
            if memory_similarity_passes(distance, space):
                # Extract just the chunk content (remove context prefix for display)
                chunk_content = doc
                if "[CHUNK_CONTENT:" in chunk_content:
                    # Extract content after the context prefix
                    content_start = chunk_content.find("[CHUNK_CONTENT:") + len("[CHUNK_CONTENT: ")
                    content_end = chunk_content.rfind("]")
                    if content_start > 0 and content_end > content_start:
                        chunk_content = chunk_content[content_start:content_end]
                
                relevant_facts.append(chunk_content)
            else:
                logger.debug(
                    "Filtered contextual fact (sim=%.3f space=%s): %s...",
                    _memory_relevance_similarity(distance, space),
                    space,
                    doc[:50],
                )
        
        # Step 4: Anti-VCT Bias (preserve existing logic)
        vct_keywords = ['vct', 'valorant', 'tournament', 'competition ruleset', 'vct26']
        query_lower = query.lower()
        is_vct_query = any(kw in query_lower for kw in vct_keywords)
        
        if not is_vct_query:
            vct_filtered = []
            for fact in relevant_facts:
                fact_lower = fact.lower()
                if any(kw in fact_lower for kw in vct_keywords):
                    logger.debug(f"Filtered out VCT fact (not VCT query): {fact[:50]}...")
                else:
                    vct_filtered.append(fact)
            relevant_facts = vct_filtered

        if not relevant_facts and documents and distances:
            logger.debug(
                "[CONTEXTUAL_SEARCH] all %d candidates rejected (space=%s cos_min_sim=%s l2_max_d=%s sample_d=%.4f)",
                len(documents),
                space,
                MEMORY_INJECTION_MIN_SIMILARITY,
                MEMORY_MAX_L2_DISTANCE,
                float(distances[0]),
            )

        logger.debug(
            "[CONTEXTUAL_SEARCH] %s results -> %s relevant (expanded=%s space=%s cos_min_sim=%s l2_max_d=%s)",
            len(documents),
            len(relevant_facts),
            expanded_query != query,
            space,
            MEMORY_INJECTION_MIN_SIMILARITY,
            MEMORY_MAX_L2_DISTANCE,
        )
        return relevant_facts[:top_k]  # Return top_k results
        
    except Exception as e:
        logger.error(f"Contextual search failed: {e}")
        return []

# ============================================
# Initialize on import
# ============================================
init_short_term_db()
load_master_profile()  # Ensure profile exists
