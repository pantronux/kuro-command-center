"""
Kuro AI V6.0 Sovereign - Intelligence Briefings Database
================================================================================
SQLite storage for daily intelligence briefings from autonomous research.

--- Header Doc ---
Purpose: Persistent store for daily intel briefings + topic watchlist.
Caller: intelligence_engine (writer), memory_coordinator (reader), main.py briefing routes.
Dependencies: sqlite3.
Main Functions: init_db(), save_briefing(), list_recent_briefings(), upsert_topic(), list_topics().
Side Effects: Writes to kuro_intelligence.db (WAL); short-lived connections closed in finally.
"""
import sqlite3
import json
import logging
import os
import threading
from datetime import datetime
from typing import List, Dict, Optional
from kuro_backend.db_utils import (
    db_retry,
    get_applied_version,
    get_connection,
    record_migration,
)

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "kuro_intelligence.db")

_SCHEMA_READY_FOR: Optional[str] = None
_SCHEMA_LOCK = threading.Lock()

def _reset_schema_ready_for_tests() -> None:
    global _SCHEMA_READY_FOR
    with _SCHEMA_LOCK:
        _SCHEMA_READY_FOR = None


def _get_connection():
    """Get a database connection with row factory."""
    conn = get_connection(DB_PATH)
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_db():
    """Initialize the intelligence briefings database schema."""
    global _SCHEMA_READY_FOR
    current_path = DB_PATH
    if _SCHEMA_READY_FOR == current_path:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY_FOR == current_path:
            return
        _init_db_locked()
        _SCHEMA_READY_FOR = current_path

def _init_db_locked():
    conn = None
    try:
        try:
            from kuro_backend import backup_manager

            backup_manager.snapshot_pre_migration(
                DB_PATH, label="intelligence"
            )
        except Exception as snap_exc:
            logger.warning("Pre-migration snapshot skipped: %s", snap_exc)
        conn = _get_connection()
        cursor = conn.cursor()

        # Check if the table already exists with the OLD schema (no username column)
        cursor.execute("PRAGMA table_info(intelligence_briefings)")
        cols = [row["name"] for row in cursor.fetchall()]

        if cols and "username" not in cols:
            # Safe migration: recreate table to add username column with UNIQUE(username, date)
            logger.info("[INTELLIGENCE] Running schema migration: adding username column via table recreation...")
            cursor.execute("ALTER TABLE intelligence_briefings RENAME TO intelligence_briefings_old")
            cursor.execute("""
                CREATE TABLE intelligence_briefings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL DEFAULT 'Pantronux',
                    date TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    raw_json_data TEXT DEFAULT '{}',
                    experimental_signals TEXT DEFAULT '[]',
                    stock_recommendations TEXT DEFAULT '[]',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, date)
                )
            """)
            cursor.execute("""
                INSERT INTO intelligence_briefings (username, date, summary_text, raw_json_data, experimental_signals, created_at)
                SELECT 'Pantronux', date, summary_text, raw_json_data, experimental_signals, created_at
                FROM intelligence_briefings_old
            """)
            cursor.execute("DROP TABLE intelligence_briefings_old")
            logger.info("[INTELLIGENCE] Schema migration complete.")
        else:
            # Create fresh if not yet existing
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS intelligence_briefings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL DEFAULT 'Pantronux',
                    date TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    raw_json_data TEXT DEFAULT '{}',
                    experimental_signals TEXT DEFAULT '[]',
                    stock_recommendations TEXT DEFAULT '[]',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, date)
                )
            """)
            
            # Check for stock_recommendations column if table exists
            cursor.execute("PRAGMA table_info(intelligence_briefings)")
            cols = [row["name"] for row in cursor.fetchall()]
            if "stock_recommendations" not in cols:
                logger.info("[INTELLIGENCE] Adding stock_recommendations column...")
                cursor.execute("ALTER TABLE intelligence_briefings ADD COLUMN stock_recommendations TEXT DEFAULT '[]'")

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_briefing_user_date ON intelligence_briefings(username, date DESC)
        """)

        # Autonomous Research: source provenance table (V1.0.0 Beta 4)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS research_sources (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                username    TEXT NOT NULL,
                chat_id     TEXT,
                query       TEXT NOT NULL,
                source_type TEXT NOT NULL CHECK(source_type IN ('scholar', 'news', 'openclaw')),
                title       TEXT,
                link        TEXT,
                snippet     TEXT,
                year        INTEGER,
                cited_by    INTEGER,
                retrieved_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_research_sources_session ON research_sources(session_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_research_sources_username ON research_sources(username, retrieved_at DESC)
        """)

        # Canvas 1 V2: internal epistemic claim audit table.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS epistemic_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                message_id TEXT,
                claim_text TEXT NOT NULL,
                source_type TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.0,
                contradiction_score REAL NOT NULL DEFAULT 0.0,
                visibility TEXT NOT NULL DEFAULT 'internal',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_epistemic_claims_session
            ON epistemic_claims(session_id, created_at DESC)
        """)

        # Canvas 1 V2: retrieval quality telemetry.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS retrieval_quality_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                retrieval_grade TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.0,
                evidence_density REAL NOT NULL DEFAULT 0.0,
                freshness_score REAL NOT NULL DEFAULT 0.0,
                contradiction_score REAL NOT NULL DEFAULT 0.0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_retrieval_quality_session
            ON retrieval_quality_log(session_id, created_at DESC)
        """)

        # Canvas 2 — multi-model / consensus telemetry.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS consensus_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                selected_role TEXT NOT NULL DEFAULT '',
                consensus_score REAL NOT NULL DEFAULT 0.0,
                consensus_label TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_consensus_session
            ON consensus_log(session_id, created_at DESC)
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_authority_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                domain TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.0,
                source_models TEXT NOT NULL DEFAULT '[]',
                canonical_summary TEXT NOT NULL DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_router_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                selected_role TEXT NOT NULL DEFAULT '',
                router_note TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS openai_model_placeholder_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                status TEXT NOT NULL DEFAULT 'placeholder',
                mode TEXT NOT NULL DEFAULT 'stub',
                api_key_present INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS backup_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_type TEXT NOT NULL CHECK(backup_type IN
                    ('nightly', 'weekly', 'pre_migration', 'manual')),
                status TEXT NOT NULL CHECK(status IN
                    ('success', 'partial', 'failed')),
                backup_path TEXT NOT NULL,
                files_backed_up INTEGER NOT NULL DEFAULT 0,
                total_size_bytes INTEGER NOT NULL DEFAULT 0,
                duration_seconds REAL NOT NULL DEFAULT 0.0,
                error_message TEXT DEFAULT NULL,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME DEFAULT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_backup_log_started
            ON backup_log(started_at DESC)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_backup_log_type_status
            ON backup_log(backup_type, status)
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS export_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                export_type TEXT NOT NULL,
                export_format TEXT NOT NULL,
                status TEXT NOT NULL,
                source_chat_id TEXT,
                source_message_ids TEXT,
                briefing_date TEXT,
                standard TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                file_path TEXT,
                file_size INTEGER,
                checksum_sha256 TEXT,
                error_message TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS export_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                export_job_id INTEGER,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute("PRAGMA table_info(export_jobs)")
        export_job_cols = [row["name"] for row in cursor.fetchall()]
        if export_job_cols and "briefing_date" not in export_job_cols:
            cursor.execute("ALTER TABLE export_jobs ADD COLUMN briefing_date TEXT")
        if export_job_cols and "standard" not in export_job_cols:
            cursor.execute("ALTER TABLE export_jobs ADD COLUMN standard TEXT")
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_export_jobs_user_created
            ON export_jobs(username, created_at DESC)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_export_jobs_status
            ON export_jobs(status)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_export_audit_user_created
            ON export_audit_log(username, created_at DESC)
            """
        )

        # Canvas 3 — operational maturity telemetry.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_trace_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_budget_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                blocked INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_risk_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                tool_name TEXT NOT NULL DEFAULT '',
                composite_risk REAL NOT NULL DEFAULT 0.0,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS source_reliability_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                credibility_score REAL NOT NULL DEFAULT 0.0,
                trustworthiness REAL NOT NULL DEFAULT 0.0,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS constitution_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                passed INTEGER NOT NULL DEFAULT 1,
                violations_json TEXT NOT NULL DEFAULT '[]',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluation_runtime_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_trail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                details TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS failed_telegram_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload_json TEXT NOT NULL,
                error_message TEXT,
                attempt_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                last_attempt_at TEXT,
                status TEXT DEFAULT 'pending'
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sentinel_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                status TEXT NOT NULL,
                details TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_failed_tg_status_attempt
            ON failed_telegram_notifications(status, attempt_count, created_at DESC)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sentinel_health_service_created
            ON sentinel_health(service, created_at DESC)
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS boundary_violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                runtime_id TEXT NOT NULL,
                username TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                reason TEXT,
                strict_mode INTEGER DEFAULT 0,
                trace_id TEXT DEFAULT '',
                ts TEXT DEFAULT (datetime('now'))
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_boundary_violations_ts
            ON boundary_violations(ts DESC)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_boundary_violations_runtime_user
            ON boundary_violations(runtime_id, username, ts DESC)
            """
        )

        if get_applied_version(conn) < 1:
            record_migration(conn, 1, "Initial schema baseline")
        conn.commit()
        logger.info(f"Intelligence briefings database initialized at {DB_PATH}")
    except Exception as e:
        logger.error(f"Failed to initialize intelligence briefings DB: {e}")
    finally:
        if conn:
            conn.close()


@db_retry()
def save_research_sources(session_id: str, username: str, chat_id: Optional[str], sources: List[Dict]) -> None:
    """Save auto-retrieved research sources for provenance tracking."""
    if not sources:
        return
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        data = []
        for s in sources:
            data.append((
                session_id, username, chat_id,
                s.get("query", ""), s.get("source_type", "scholar"),
                s.get("title"), s.get("link"), s.get("snippet"),
                s.get("year"), s.get("cited_by")
            ))
        cursor.executemany(
            """INSERT INTO research_sources 
               (session_id, username, chat_id, query, source_type, title, link, snippet, year, cited_by) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            data
        )
        conn.commit()
        logger.info(f"[INTELLIGENCE] {len(sources)} research sources saved for {username} in session {session_id}")
    except Exception as e:
        logger.error(f"Failed to save research sources: {e}")
    finally:
        if conn:
            conn.close()


@db_retry()
def save_epistemic_claims(session_id: str, message_id: str, claims: List[Dict]) -> None:
    if not claims:
        return
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        rows = []
        for c in claims:
            rows.append(
                (
                    session_id,
                    message_id,
                    c.get("text", ""),
                    c.get("source_type", "unknown"),
                    float(c.get("confidence", 0.0) or 0.0),
                    float(c.get("contradiction_score", 0.0) or 0.0),
                    c.get("visibility", "internal"),
                )
            )
        cursor.executemany(
            """
            INSERT INTO epistemic_claims
                (session_id, message_id, claim_text, source_type, confidence, contradiction_score, visibility)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save epistemic claims: {e}")
    finally:
        if conn:
            conn.close()


@db_retry()
def save_retrieval_quality_log(
    *,
    session_id: str,
    retrieval_grade: str,
    confidence: float,
    evidence_density: float,
    freshness_score: float,
    contradiction_score: float,
) -> None:
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO retrieval_quality_log
                (session_id, retrieval_grade, confidence, evidence_density, freshness_score, contradiction_score)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                retrieval_grade,
                float(confidence),
                float(evidence_density),
                float(freshness_score),
                float(contradiction_score),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save retrieval quality log: {e}")
    finally:
        if conn:
            conn.close()


@db_retry()
def save_model_router_log(*, session_id: str, selected_role: str, router_note: str, payload: Dict) -> None:
    conn = None
    try:
        conn = _get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO model_router_log (session_id, selected_role, router_note, payload_json) VALUES (?, ?, ?, ?)",
            (session_id, selected_role, router_note, json.dumps(payload or {}, ensure_ascii=False)),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save model router log: {e}")
    finally:
        if conn:
            conn.close()


@db_retry()
def save_consensus_log(*, session_id: str, selected_role: str, consensus_score: float, consensus_label: str, payload: Dict) -> None:
    conn = None
    try:
        conn = _get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO consensus_log (session_id, selected_role, consensus_score, consensus_label, payload_json) VALUES (?, ?, ?, ?, ?)",
            (session_id, selected_role, float(consensus_score), consensus_label, json.dumps(payload or {}, ensure_ascii=False)),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save consensus log: {e}")
    finally:
        if conn:
            conn.close()


@db_retry()
def save_memory_authority_log(*, session_id: str, payload: Dict) -> None:
    conn = None
    try:
        conn = _get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO memory_authority_log (session_id, domain, confidence, source_models, canonical_summary) VALUES (?, ?, ?, ?, ?)",
            (
                session_id,
                str(payload.get("domain", "")),
                float(payload.get("confidence", 0.0) or 0.0),
                json.dumps(payload.get("source_models", []), ensure_ascii=False),
                str(payload.get("canonical_summary", "")),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save memory authority log: {e}")
    finally:
        if conn:
            conn.close()


@db_retry()
def save_openai_model_placeholder_log(*, session_id: str, payload: Dict) -> None:
    conn = None
    try:
        conn = _get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO openai_model_placeholder_log (session_id, status, mode, api_key_present, payload_json) VALUES (?, ?, ?, ?, ?)",
            (
                session_id,
                str(payload.get("status", "placeholder")),
                str(payload.get("mode", "stub")),
                1 if bool(payload.get("api_key_present", False)) else 0,
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save OpenAI Model placeholder log: {e}")
    finally:
        if conn:
            conn.close()


@db_retry()
def save_tool_trace_log(*, session_id: str, payload: Dict) -> None:
    conn = None
    try:
        conn = _get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO tool_trace_log (session_id, payload_json) VALUES (?, ?)",
            (session_id, json.dumps(payload or {}, ensure_ascii=False)),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save tool trace log: {e}")
    finally:
        if conn:
            conn.close()


@db_retry()
def save_tool_budget_log(*, session_id: str, payload: Dict) -> None:
    conn = None
    try:
        conn = _get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO tool_budget_log (session_id, blocked, payload_json) VALUES (?, ?, ?)",
            (
                session_id,
                1 if bool((payload or {}).get("blocked", False)) else 0,
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save tool budget log: {e}")
    finally:
        if conn:
            conn.close()


@db_retry()
def save_tool_risk_log(*, session_id: str, tool_name: str, composite_risk: float, payload: Dict) -> None:
    conn = None
    try:
        conn = _get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO tool_risk_log (session_id, tool_name, composite_risk, payload_json) VALUES (?, ?, ?, ?)",
            (session_id, tool_name, float(composite_risk), json.dumps(payload or {}, ensure_ascii=False)),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save tool risk log: {e}")
    finally:
        if conn:
            conn.close()


@db_retry()
def save_source_reliability_log(*, session_id: str, payload: Dict) -> None:
    conn = None
    try:
        conn = _get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO source_reliability_log (session_id, credibility_score, trustworthiness, payload_json) VALUES (?, ?, ?, ?)",
            (
                session_id,
                float((payload or {}).get("credibility_score", 0.0) or 0.0),
                float((payload or {}).get("retrieval_trustworthiness", 0.0) or 0.0),
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save source reliability log: {e}")
    finally:
        if conn:
            conn.close()


@db_retry()
def save_constitution_audit_log(*, session_id: str, payload: Dict) -> None:
    conn = None
    try:
        conn = _get_connection()
        c = conn.cursor()
        violations = (payload or {}).get("violations", [])
        c.execute(
            "INSERT INTO constitution_audit_log (session_id, passed, violations_json, payload_json) VALUES (?, ?, ?, ?)",
            (
                session_id,
                1 if not violations else 0,
                json.dumps(violations or [], ensure_ascii=False),
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save constitution audit log: {e}")
    finally:
        if conn:
            conn.close()


@db_retry()
def save_evaluation_runtime_log(*, session_id: str, payload: Dict) -> None:
    conn = None
    try:
        conn = _get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO evaluation_runtime_log (session_id, payload_json) VALUES (?, ?)",
            (session_id, json.dumps(payload or {}, ensure_ascii=False)),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to save evaluation runtime log: {e}")
    finally:
        if conn:
            conn.close()

def get_research_sources(username: str, since_hours: int = 24) -> List[Dict]:
    """Get research sources retrieved in the last N hours."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM research_sources WHERE username = ? AND retrieved_at >= datetime('now', '-' || ? || ' hours') ORDER BY retrieved_at DESC",
            (username, since_hours)
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get research sources: {e}")
        return []
    finally:
        if conn:
            conn.close()

def search_sources_by_query(username: str, query_fragment: str) -> List[Dict]:
    """Search research sources by query fragment."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM research_sources WHERE username = ? AND (query LIKE ? OR title LIKE ? OR snippet LIKE ?) ORDER BY retrieved_at DESC",
            (username, f"%{query_fragment}%", f"%{query_fragment}%", f"%{query_fragment}%")
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to search research sources: {e}")
        return []
    finally:
        if conn:
            conn.close()


@db_retry()
def save_briefing(date: str, summary_text: str, raw_json_data: Dict, experimental_signals: List[str], stock_recommendations: List[Dict] = None, username: str = "Pantronux") -> bool:
    """Save a daily intelligence briefing for a specific user."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT OR REPLACE INTO intelligence_briefings 
               (username, date, summary_text, raw_json_data, experimental_signals, stock_recommendations) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (username, date, summary_text, json.dumps(raw_json_data, ensure_ascii=False), json.dumps(experimental_signals), json.dumps(stock_recommendations or []))
        )
        conn.commit()
        logger.info(f"[INTELLIGENCE] Briefing saved for {username} on {date}")
        return True
    except Exception as e:
        logger.error(f"Failed to save briefing: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_briefings(limit: int = 20, offset: int = 0, username: str = "Pantronux") -> List[Dict]:
    """Get recent briefings for a specific user with pagination."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM intelligence_briefings WHERE username = ? ORDER BY date DESC LIMIT ? OFFSET ?",
            (username, limit, offset)
        )
        rows = cursor.fetchall()
        
        briefings = []
        for row in rows:
            briefings.append({
                "id": row["id"],
                "date": row["date"],
                "summary_text": row["summary_text"],
                "raw_json_data": json.loads(row["raw_json_data"]),
                "experimental_signals": json.loads(row["experimental_signals"]),
                "stock_recommendations": json.loads(row["stock_recommendations"] or '[]'),
                "created_at": row["created_at"]
            })
        
        return briefings
    except Exception as e:
        logger.error(f"Failed to get briefings: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_briefing_by_date(date: str, username: str = "Pantronux") -> Optional[Dict]:
    """Get a specific briefing by date for a specific user."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM intelligence_briefings WHERE date = ? AND username = ?", (date, username))
        row = cursor.fetchone()
        
        if row:
            return {
                "id": row["id"],
                "date": row["date"],
                "summary_text": row["summary_text"],
                "raw_json_data": json.loads(row["raw_json_data"]),
                "experimental_signals": json.loads(row["experimental_signals"]),
                "stock_recommendations": json.loads(row["stock_recommendations"] or '[]'),
                "created_at": row["created_at"]
            }
        return None
    except Exception as e:
        logger.error(f"Failed to get briefing: {e}")
        return None
    finally:
        if conn:
            conn.close()

def search_briefings(query: str, username: str = "Pantronux", limit: int = 20) -> List[Dict]:
    """Search briefings by keyword for a specific user."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM intelligence_briefings WHERE username = ? AND summary_text LIKE ? ORDER BY date DESC LIMIT ?",
            (username, f"%{query}%", limit)
        )
        rows = cursor.fetchall()
        
        briefings = []
        for row in rows:
            briefings.append({
                "id": row["id"],
                "date": row["date"],
                "summary_text": row["summary_text"],
                "raw_json_data": json.loads(row["raw_json_data"]),
                "experimental_signals": json.loads(row["experimental_signals"]),
                "stock_recommendations": json.loads(row["stock_recommendations"] or '[]'),
                "created_at": row["created_at"]
            })
        
        return briefings
    except Exception as e:
        logger.error(f"Failed to search briefings: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_total_count(username: str = "Pantronux") -> int:
    """Get total count of briefings for a specific user."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM intelligence_briefings WHERE username = ?", (username,))
        return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Failed to get briefing count: {e}")
        return 0
    finally:
        if conn:
            conn.close()


@db_retry()
def log_backup_start(backup_type: str, backup_path: str) -> int:
    """Insert an audit row for the start of a backup run."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO backup_log (
                backup_type, status, backup_path, files_backed_up,
                total_size_bytes, duration_seconds, error_message, completed_at
            ) VALUES (?, 'partial', ?, 0, 0, 0.0, NULL, NULL)
            """,
            (backup_type, backup_path),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        if conn:
            conn.close()


@db_retry()
def log_backup_complete(
    log_id: int,
    status: str,
    files_count: int,
    size_bytes: int,
    duration_s: float,
    error: str | None = None,
) -> None:
    """Finalize a backup audit row."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE backup_log
            SET status = ?, files_backed_up = ?, total_size_bytes = ?,
                duration_seconds = ?, error_message = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, files_count, size_bytes, duration_s, error, log_id),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


def get_backup_history(limit: int = 30) -> List[Dict]:
    """Return recent backup audit rows."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, backup_type, status, backup_path, files_backed_up,
                   total_size_bytes, duration_seconds, error_message,
                   started_at, completed_at
            FROM backup_log
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get backup history: {e}")
        return []
    finally:
        if conn:
            conn.close()


def get_last_backup_status() -> Optional[Dict]:
    """Return the most recent backup audit row."""
    rows = get_backup_history(limit=1)
    return rows[0] if rows else None


@db_retry()
def create_export_job(
    username: str,
    export_type: str,
    export_format: str,
    source_chat_id: Optional[str],
    source_message_ids: List[int] | None = None,
    briefing_date: Optional[str] = None,
    standard: Optional[str] = None,
) -> int:
    """Insert a new export job row and return its ID."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO export_jobs (
                username, export_type, export_format, status, source_chat_id,
                source_message_ids, briefing_date, standard, created_at
            ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                username,
                export_type,
                export_format,
                source_chat_id,
                json.dumps(source_message_ids or []),
                briefing_date,
                standard,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        if conn:
            conn.close()


@db_retry()
def mark_export_job_running(job_id: int) -> None:
    """Mark an export job as running."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE export_jobs SET status = 'running' WHERE id = ?",
            (job_id,),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


@db_retry()
def mark_export_job_completed(
    job_id: int,
    file_path: str,
    file_size: int,
    checksum_sha256: str,
) -> None:
    """Finalize a completed export job."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE export_jobs
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP, file_path = ?,
                file_size = ?, checksum_sha256 = ?, error_message = NULL
            WHERE id = ?
            """,
            (file_path, file_size, checksum_sha256, job_id),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


@db_retry()
def mark_export_job_failed(job_id: int, error_message: str) -> None:
    """Finalize a failed export job."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE export_jobs
            SET status = 'failed', completed_at = CURRENT_TIMESTAMP, error_message = ?
            WHERE id = ?
            """,
            (error_message, job_id),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


def get_export_job(job_id: int) -> Optional[Dict]:
    """Return a single export job row."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM export_jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error("Failed to get export job: %s", e)
        return None
    finally:
        if conn:
            conn.close()


def list_export_jobs(username: str, limit: int = 20) -> List[Dict]:
    """Return recent export jobs for a user."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM export_jobs
            WHERE username = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (username, limit),
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error("Failed to list export jobs: %s", e)
        return []
    finally:
        if conn:
            conn.close()


@db_retry()
def log_export_audit(
    username: str,
    action: str,
    export_job_id: Optional[int],
    metadata: Dict,
) -> None:
    """Insert an export audit row."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO export_audit_log (
                username, action, export_job_id, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                username,
                action,
                export_job_id,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


@db_retry()
def add_audit_trail(action: str, details: str = "") -> None:
    """Append one audit trail event for platform-level operational traces."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO audit_trail (action, details) VALUES (?, ?)",
            (str(action or ""), str(details or "")),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("Failed to append intelligence audit trail: %s", exc)
    finally:
        if conn:
            conn.close()


@db_retry()
def log_failed_notification(payload_json: str, error_message: str) -> int:
    """Insert a failed Telegram payload into DLQ and return row id."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO failed_telegram_notifications (
                payload_json, error_message, attempt_count, status, last_attempt_at
            ) VALUES (?, ?, 0, 'pending', datetime('now'))
            """,
            (payload_json, error_message),
        )
        conn.commit()
        return int(cursor.lastrowid or 0)
    finally:
        if conn:
            conn.close()


def get_pending_failed_notifications(max_attempts: int = 5) -> List[Dict]:
    """Return pending Telegram DLQ rows below retry-attempt cap."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM failed_telegram_notifications
            WHERE status = 'pending' AND attempt_count < ?
            ORDER BY created_at ASC, id ASC
            """,
            (int(max_attempts),),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        if conn:
            conn.close()


@db_retry()
def update_notification_attempt(notification_id: int, error_message: Optional[str], success: bool = False) -> None:
    """Update attempt counters after DLQ replay attempt."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        if success:
            cursor.execute(
                """
                UPDATE failed_telegram_notifications
                SET status = 'sent', error_message = NULL, last_attempt_at = datetime('now')
                WHERE id = ?
                """,
                (int(notification_id),),
            )
        else:
            cursor.execute(
                """
                UPDATE failed_telegram_notifications
                SET attempt_count = attempt_count + 1,
                    error_message = ?,
                    last_attempt_at = datetime('now')
                WHERE id = ?
                """,
                (error_message, int(notification_id)),
            )
        conn.commit()
    finally:
        if conn:
            conn.close()


@db_retry()
def mark_notification_dead(notification_id: int) -> None:
    """Mark a DLQ payload as dead after max retries."""
    init_db()
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE failed_telegram_notifications SET status = 'dead', last_attempt_at = datetime('now') WHERE id = ?",
            (int(notification_id),),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


@db_retry()
def log_boundary_violation(
    runtime_id: str,
    username: str,
    resource_type: str,
    resource_id: str,
    reason: str,
    strict_mode: bool = False,
    trace_id: str = "",
) -> None:
    init_db()
    conn = None
    try:
        conn = _get_connection()
        conn.execute(
            """
            INSERT INTO boundary_violations
                (runtime_id, username, resource_type, resource_id, reason, strict_mode, trace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                runtime_id,
                username,
                resource_type,
                resource_id,
                reason,
                1 if strict_mode else 0,
                trace_id,
            ),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


def get_recent_boundary_violations(limit: int = 100) -> List[Dict]:
    init_db()
    safe_limit = max(1, min(500, int(limit)))
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM boundary_violations
            ORDER BY ts DESC, id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        if conn:
            conn.close()

# Initialize on import
init_db()
