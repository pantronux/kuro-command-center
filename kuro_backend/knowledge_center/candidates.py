"""SQLite store for approved and candidate KRC knowledge."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from kuro_backend.config import settings
from kuro_backend.knowledge_center.redaction import redact_public_text
from kuro_backend.knowledge_center.schemas import CandidateKnowledgeRequest, KnowledgeIngestRequest
from kuro_backend.storage.connection import StorageConnectionManager


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def default_knowledge_db_path() -> str:
    configured = os.getenv("KURO_KNOWLEDGE_DB_PATH", "").strip()
    if configured:
        return configured
    return str(Path(getattr(settings, "WORKING_DIR", "") or ".").expanduser() / "kuro_knowledge_center.db")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class KnowledgeStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or default_knowledge_db_path())
        self.connection_manager = StorageConnectionManager(self.db_path)

    def init_db(self) -> None:
        with self.connection_manager.transaction() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS approved_knowledge (
                    knowledge_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.75,
                    status TEXT NOT NULL DEFAULT 'approved'
                        CHECK (status IN ('approved','retired')),
                    citations_json TEXT NOT NULL DEFAULT '[]',
                    candidate_id TEXT DEFAULT '',
                    approved_by TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    source_app TEXT NOT NULL,
                    source_chat_id TEXT,
                    domain TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','approved','rejected')),
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewer TEXT
                );

                CREATE TABLE IF NOT EXISTS knowledge_audit (
                    audit_id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    auth_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    trace_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_ingest_jobs (
                    job_id TEXT PRIMARY KEY,
                    source_app TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content_preview TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued','processing','completed','failed','retrying')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_approved_knowledge_search
                    ON approved_knowledge(status, domain, updated_at);
                CREATE INDEX IF NOT EXISTS idx_knowledge_candidates_status
                    ON knowledge_candidates(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_knowledge_ingest_jobs_status
                    ON knowledge_ingest_jobs(status, updated_at);
                """
            )

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        self.init_db()
        return self.connection_manager.connect(read_only=read_only)

    def approved_count(self) -> int:
        self.init_db()
        with self.connection_manager.transaction(read_only=True) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM approved_knowledge WHERE status = 'approved'"
            ).fetchone()
        return int(row["count"] if row else 0)

    def candidate_count(self, status: str = "pending") -> int:
        self.init_db()
        with self.connection_manager.transaction(read_only=True) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM knowledge_candidates WHERE status = ?",
                (status,),
            ).fetchone()
        return int(row["count"] if row else 0)

    def upsert_approved(
        self,
        *,
        title: str,
        summary: str,
        content: str,
        domain: str,
        source_type: str,
        source_id: str,
        confidence: float = 0.75,
        citations: Optional[List[Dict[str, Any]]] = None,
        approved_by: str = "",
        candidate_id: str = "",
        knowledge_id: str | None = None,
    ) -> str:
        self.init_db()
        now = utc_now_iso()
        kid = knowledge_id or new_id("kn")
        clean_summary = redact_public_text(summary or content, max_chars=2000)
        clean_content = redact_public_text(content, max_chars=12000)
        clean_title = redact_public_text(title or clean_summary[:120] or "Approved knowledge", max_chars=240)
        with self.connection_manager.transaction() as conn:
            conn.execute(
                """
                INSERT INTO approved_knowledge (
                    knowledge_id, title, summary, content, domain, source_type,
                    source_id, confidence, status, citations_json, candidate_id,
                    approved_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?, ?, ?, ?)
                ON CONFLICT(knowledge_id) DO UPDATE SET
                    title=excluded.title,
                    summary=excluded.summary,
                    content=excluded.content,
                    domain=excluded.domain,
                    source_type=excluded.source_type,
                    source_id=excluded.source_id,
                    confidence=excluded.confidence,
                    status='approved',
                    citations_json=excluded.citations_json,
                    approved_by=excluded.approved_by,
                    updated_at=excluded.updated_at
                """,
                (
                    kid,
                    clean_title,
                    clean_summary,
                    clean_content,
                    (domain or "research").strip().lower()[:64],
                    redact_public_text(source_type or "manual", max_chars=80),
                    redact_public_text(source_id or kid, max_chars=160),
                    max(0.0, min(1.0, float(confidence))),
                    json.dumps(citations or [], ensure_ascii=False, sort_keys=True),
                    candidate_id,
                    approved_by,
                    now,
                    now,
                ),
            )
        return kid

    def search_approved(
        self,
        *,
        query: str = "",
        domains: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        self.init_db()
        sql = [
            "SELECT * FROM approved_knowledge WHERE status = 'approved'",
        ]
        params: List[Any] = []
        clean_domains = [d.strip().lower() for d in domains or [] if d.strip()]
        if clean_domains:
            placeholders = ",".join("?" for _ in clean_domains)
            sql.append(f"AND domain IN ({placeholders})")
            params.extend(clean_domains)
        if query.strip():
            like = f"%{query.strip()}%"
            sql.append("AND (title LIKE ? OR summary LIKE ? OR content LIKE ?)")
            params.extend([like, like, like])
        sql.append("ORDER BY confidence DESC, updated_at DESC LIMIT ?")
        params.append(max(1, min(50, int(limit))))
        with self.connection_manager.transaction(read_only=True) as conn:
            rows = conn.execute(" ".join(sql), tuple(params)).fetchall()
        return [self._approved_row_to_result(dict(row)) for row in rows]

    def source_metadata(self, source_id: str) -> Optional[Dict[str, Any]]:
        self.init_db()
        safe_source_id = redact_public_text(source_id, max_chars=160)
        with self.connection_manager.transaction(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT knowledge_id, title, domain, source_type, source_id, citations_json, updated_at
                FROM approved_knowledge
                WHERE status = 'approved' AND source_id = ?
                ORDER BY updated_at DESC
                """,
                (safe_source_id,),
            ).fetchall()
        if not rows:
            return None
        first = dict(rows[0])
        return {
            "source_id": first["source_id"],
            "source_type": first["source_type"],
            "knowledge_ids": [row["knowledge_id"] for row in rows],
            "domains": sorted({row["domain"] for row in rows}),
            "citations": [
                citation
                for row in rows
                for citation in json.loads(row["citations_json"] or "[]")
                if isinstance(citation, dict)
            ],
            "updated_at": first["updated_at"],
        }

    def create_candidate(self, payload: CandidateKnowledgeRequest) -> Dict[str, Any]:
        self.init_db()
        now = utc_now_iso()
        candidate_id = new_id("kcand")
        with self.connection_manager.transaction() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_candidates (
                    candidate_id, source_app, source_chat_id, domain, title, content,
                    reason, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    candidate_id,
                    redact_public_text(payload.source_app, max_chars=80),
                    redact_public_text(payload.source_chat_id or "", max_chars=160) or None,
                    (payload.domain or "research").strip().lower()[:64],
                    redact_public_text(payload.title or "", max_chars=240),
                    redact_public_text(payload.content, max_chars=32000),
                    redact_public_text(payload.reason or "", max_chars=1000),
                    now,
                ),
            )
        return self.get_candidate(candidate_id) or {"candidate_id": candidate_id}

    def get_candidate(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        self.init_db()
        with self.connection_manager.transaction(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_candidates(self, *, status: str = "pending", limit: int = 50) -> List[Dict[str, Any]]:
        self.init_db()
        with self.connection_manager.transaction(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM knowledge_candidates
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, max(1, min(200, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    def approve_candidate(
        self,
        candidate_id: str,
        *,
        reviewer: str,
        title: str = "",
        summary: str = "",
        confidence: float = 0.75,
    ) -> Dict[str, Any]:
        candidate = self.get_candidate(candidate_id)
        if not candidate:
            raise KeyError(candidate_id)
        if candidate["status"] != "pending":
            raise ValueError("candidate is not pending")
        knowledge_id = self.upsert_approved(
            title=title or candidate.get("title") or "Approved candidate knowledge",
            summary=summary or candidate.get("content", "")[:1200],
            content=candidate.get("content", ""),
            domain=candidate.get("domain") or "research",
            source_type=f"candidate:{candidate.get('source_app') or 'unknown'}",
            source_id=candidate_id,
            confidence=confidence,
            approved_by=reviewer,
            candidate_id=candidate_id,
        )
        now = utc_now_iso()
        with self.connection_manager.transaction() as conn:
            conn.execute(
                """
                UPDATE knowledge_candidates
                SET status = 'approved', reviewed_at = ?, reviewer = ?
                WHERE candidate_id = ?
                """,
                (now, reviewer, candidate_id),
            )
        return {"candidate_id": candidate_id, "knowledge_id": knowledge_id, "status": "approved"}

    def reject_candidate(self, candidate_id: str, *, reviewer: str) -> Dict[str, Any]:
        candidate = self.get_candidate(candidate_id)
        if not candidate:
            raise KeyError(candidate_id)
        if candidate["status"] != "pending":
            raise ValueError("candidate is not pending")
        now = utc_now_iso()
        with self.connection_manager.transaction() as conn:
            conn.execute(
                """
                UPDATE knowledge_candidates
                SET status = 'rejected', reviewed_at = ?, reviewer = ?
                WHERE candidate_id = ?
                """,
                (now, reviewer, candidate_id),
            )
        return {"candidate_id": candidate_id, "status": "rejected"}

    def log_audit(self, *, actor: str, auth_type: str, action: str, trace_id: str = "") -> None:
        self.init_db()
        with self.connection_manager.transaction() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_audit (audit_id, actor, auth_type, action, trace_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (new_id("kaud"), actor, auth_type, action, trace_id, utc_now_iso()),
            )

    def create_ingest_job(self, payload: KnowledgeIngestRequest) -> Dict[str, Any]:
        self.init_db()
        now = utc_now_iso()
        job_id = new_id("king")
        preview = redact_public_text(payload.content or payload.title, max_chars=1000)
        metadata = dict(payload.metadata or {})
        metadata.pop("content", None)
        metadata.pop("raw_content", None)
        with self.connection_manager.transaction() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_ingest_jobs (
                    job_id, source_app, domain, source_type, title, content_preview,
                    metadata_json, status, attempts, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?)
                """,
                (
                    job_id,
                    redact_public_text(payload.source_app, max_chars=80),
                    (payload.domain or "research.paper").strip().lower()[:80],
                    redact_public_text(payload.source_type or "document", max_chars=80),
                    redact_public_text(payload.title, max_chars=500),
                    preview,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
        return self.get_ingest_job(job_id) or {"job_id": job_id, "status": "queued"}

    def list_ingest_jobs(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        self.init_db()
        with self.connection_manager.transaction(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM knowledge_ingest_jobs
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (max(1, min(200, int(limit))),),
            ).fetchall()
        return [self._ingest_job_row(dict(row)) for row in rows]

    def get_ingest_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        self.init_db()
        with self.connection_manager.transaction(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_ingest_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self._ingest_job_row(dict(row)) if row else None

    def retry_ingest_job(self, job_id: str) -> Dict[str, Any]:
        job = self.get_ingest_job(job_id)
        if not job:
            raise KeyError(job_id)
        now = utc_now_iso()
        with self.connection_manager.transaction() as conn:
            conn.execute(
                """
                UPDATE knowledge_ingest_jobs
                SET status = 'retrying', attempts = attempts + 1, updated_at = ?
                WHERE job_id = ?
                """,
                (now, job_id),
            )
        return self.get_ingest_job(job_id) or {"job_id": job_id, "status": "retrying"}

    @staticmethod
    def _ingest_job_row(row: Dict[str, Any]) -> Dict[str, Any]:
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
        except Exception:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        return {
            "job_id": row.get("job_id", ""),
            "source_app": redact_public_text(row.get("source_app") or "", max_chars=80),
            "domain": row.get("domain") or "",
            "source_type": redact_public_text(row.get("source_type") or "", max_chars=80),
            "title": redact_public_text(row.get("title") or "", max_chars=500),
            "content_preview": redact_public_text(row.get("content_preview") or "", max_chars=1000),
            "metadata": metadata,
            "status": row.get("status") or "queued",
            "attempts": int(row.get("attempts") or 0),
            "error_message": redact_public_text(row.get("error_message") or "", max_chars=1000),
            "created_at": row.get("created_at") or "",
            "updated_at": row.get("updated_at") or "",
        }

    @staticmethod
    def _approved_row_to_result(row: Dict[str, Any]) -> Dict[str, Any]:
        citations = json.loads(row.get("citations_json") or "[]")
        if not isinstance(citations, list):
            citations = []
        return {
            "knowledge_id": row["knowledge_id"],
            "title": redact_public_text(row.get("title") or "", max_chars=240),
            "summary": redact_public_text(row.get("summary") or "", max_chars=2000),
            "domain": row.get("domain") or "research",
            "source_type": redact_public_text(row.get("source_type") or "manual", max_chars=80),
            "source_id": redact_public_text(row.get("source_id") or "", max_chars=160),
            "confidence": float(row.get("confidence") or 0.0),
            "updated_at": row.get("updated_at") or "",
            "citations": [c for c in citations if isinstance(c, dict)],
            "content": redact_public_text(row.get("content") or "", max_chars=12000),
        }
