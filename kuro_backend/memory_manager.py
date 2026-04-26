"""
Kuro AI V6.0 Sovereign - Memory Manager [2026-04-17]
================================================================================
Kuro Cognitive Memory Engine V3.0 - Contextual RAG Architecture
TIER 1: Short-Term Buffer (SQLite) - Last 20 interactions
TIER 2: Semantic Long-Term Memory (Mem0) - Context-enriched embedded facts
TIER 3: Structured Knowledge Base (JSON) - Permanent master profile (ABSOLUTE TRUTH)

--- Header Doc ---
Purpose: Three-tier cognitive memory orchestration (short-term SQLite, semantic Mem0, master-profile JSON).
Caller: memory_coordinator, langgraph_core, core.py, services/core_service, dreaming_worker.
Dependencies: sqlite3, chromadb, google-genai (embeddings + summaries), embedding_cache, perpetual_memory.
Main Functions: add_interaction(), retrieve_context(), semantic_upsert_fact(), extract_facts(), cleanup_old_facts(), load_master_profile().
Side Effects: Writes to kuro_short_term.db, Mem0 vector store, master_profile.json; Gemini embedding + summarization calls; background decay threads.

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
- Context Ranking: Relevance threshold filtering for Mem0 results
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
IMPORTANCE_THRESHOLD = 7  # Only store to Mem0 if importance > 7
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
# TIER 2: Semantic Long-Term Memory (Mem0)
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

def get_memory_stats() -> Dict:
    """Returns statistics about the memory system."""
    profile = load_master_profile()
    short_term_count = len(get_short_term())
    
    # Mem0 count
    long_term_count = 0
    try:
        from kuro_backend.perpetual_memory import get_memory_client
        client = get_memory_client()
        memories = client.get_all_memories(limit=1000)
        if memories:
            long_term_count = len(memories)
    except Exception:
        pass
    
    return {
        "tier1_short_term": {"type": "SQLite", "entries": short_term_count, "limit": SHORT_TERM_LIMIT},
        "tier2_long_term": {"type": "Mem0", "entries": long_term_count},
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
    based on the last 3 chat messages before searching Mem0.
    
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



# ============================================
# Initialize on import
# ============================================
init_short_term_db()
load_master_profile()  # Ensure profile exists
