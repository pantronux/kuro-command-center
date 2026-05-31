"""SQLite storage for KRC research artifacts."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from kuro_backend.config import settings


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def default_research_db_path() -> str:
    configured = os.getenv("KURO_RESEARCH_DB_PATH", "").strip()
    if configured:
        return configured
    return str(Path(getattr(settings, "WORKING_DIR", "") or ".").expanduser() / "kuro_research_center.db")


class ResearchStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or default_research_db_path())

    def _connect(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_projects (
                    project_id TEXT PRIMARY KEY,
                    owner_username TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_sources (
                    source_id TEXT PRIMARY KEY,
                    owner_username TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    authors_json TEXT NOT NULL DEFAULT '[]',
                    year INTEGER,
                    venue TEXT NOT NULL DEFAULT '',
                    doi TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    file_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    provenance_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_notes (
                    note_id TEXT PRIMARY KEY,
                    owner_username TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    source_id TEXT NOT NULL DEFAULT '',
                    note_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_claims (
                    claim_id TEXT PRIMARY KEY,
                    owner_username TEXT NOT NULL,
                    source_id TEXT NOT NULL DEFAULT '',
                    project_id TEXT NOT NULL,
                    claim_text TEXT NOT NULL,
                    claim_type TEXT NOT NULL DEFAULT 'finding',
                    evidence_quote TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    page_or_section TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_questions (
                    question_id TEXT PRIMARY KEY,
                    owner_username TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    rationale TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS novelty_gaps (
                    gap_id TEXT PRIMARY KEY,
                    owner_username TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    related_sources_json TEXT NOT NULL DEFAULT '[]',
                    strength TEXT NOT NULL DEFAULT 'medium',
                    risk TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS argument_nodes (
                    node_id TEXT PRIMARY KEY,
                    owner_username TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    node_type TEXT NOT NULL DEFAULT 'claim',
                    label TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    source_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS argument_edges (
                    edge_id TEXT PRIMARY KEY,
                    owner_username TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    from_node_id TEXT NOT NULL,
                    to_node_id TEXT NOT NULL,
                    relation TEXT NOT NULL DEFAULT 'supports',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS advisor_sessions (
                    advisor_session_id TEXT PRIMARY KEY,
                    owner_username TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    persona_id TEXT NOT NULL DEFAULT 'phd_advisor',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_research_projects_owner ON research_projects(owner_username, updated_at);
                CREATE INDEX IF NOT EXISTS idx_paper_sources_project ON paper_sources(owner_username, project_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_research_claims_project ON research_claims(owner_username, project_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_research_questions_project ON research_questions(owner_username, project_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_novelty_gaps_project ON novelty_gaps(owner_username, project_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_argument_nodes_project ON argument_nodes(owner_username, project_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_argument_edges_project ON argument_edges(owner_username, project_id, created_at);
                """
            )

    def _row(self, row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
        return dict(row) if row else None

    def _rows(self, rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
        return [dict(row) for row in rows]

    def create_project(self, *, owner: str, title: str, description: str = "", status: str = "active") -> Dict[str, Any]:
        self.init_db()
        now = utc_now_iso()
        project_id = new_id("rproj")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_projects (project_id, owner_username, title, description, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, owner, title, description, status or "active", now, now),
            )
        return self.get_project(owner=owner, project_id=project_id) or {"project_id": project_id}

    def list_projects(self, *, owner: str) -> List[Dict[str, Any]]:
        self.init_db()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_projects WHERE owner_username = ? ORDER BY updated_at DESC",
                (owner,),
            ).fetchall()
        return self._rows(rows)

    def get_project(self, *, owner: str, project_id: str) -> Optional[Dict[str, Any]]:
        self.init_db()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_projects WHERE owner_username = ? AND project_id = ?",
                (owner, project_id),
            ).fetchone()
        return self._row(row)

    def update_project(self, *, owner: str, project_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self.init_db()
        allowed = {k: v for k, v in updates.items() if k in {"title", "description", "status"} and v is not None}
        if not allowed:
            return self.get_project(owner=owner, project_id=project_id)
        allowed["updated_at"] = utc_now_iso()
        assignments = ", ".join(f"{key} = ?" for key in allowed)
        values = list(allowed.values()) + [owner, project_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE research_projects SET {assignments} WHERE owner_username = ? AND project_id = ?",
                values,
            )
        return self.get_project(owner=owner, project_id=project_id)

    def _ensure_project(self, *, owner: str, project_id: str) -> None:
        if not self.get_project(owner=owner, project_id=project_id):
            raise KeyError(project_id)

    def create_source(self, *, owner: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_project(owner=owner, project_id=payload["project_id"])
        now = utc_now_iso()
        source_id = new_id("rsrc")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_sources (
                    source_id, owner_username, project_id, title, authors_json, year, venue,
                    doi, url, file_ref, status, provenance_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    owner,
                    payload["project_id"],
                    payload["title"],
                    json.dumps(payload.get("authors") or [], ensure_ascii=False),
                    payload.get("year"),
                    payload.get("venue") or "",
                    payload.get("doi") or "",
                    payload.get("url") or "",
                    payload.get("file_ref") or "",
                    payload.get("status") or "candidate",
                    json.dumps(payload.get("provenance") or {}, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
        return self.get_source(owner=owner, source_id=source_id) or {"source_id": source_id}

    def list_sources(self, *, owner: str, project_id: str | None = None) -> List[Dict[str, Any]]:
        self.init_db()
        sql = "SELECT * FROM paper_sources WHERE owner_username = ?"
        params: List[Any] = [owner]
        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        sql += " ORDER BY updated_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return self._rows(rows)

    def get_source(self, *, owner: str, source_id: str) -> Optional[Dict[str, Any]]:
        self.init_db()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM paper_sources WHERE owner_username = ? AND source_id = ?",
                (owner, source_id),
            ).fetchone()
        return self._row(row)

    def create_claim(self, *, owner: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_project(owner=owner, project_id=payload["project_id"])
        claim_id = new_id("rclaim")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_claims (
                    claim_id, owner_username, source_id, project_id, claim_text, claim_type,
                    evidence_quote, confidence, page_or_section, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    owner,
                    payload.get("source_id") or "",
                    payload["project_id"],
                    payload["claim_text"],
                    payload.get("claim_type") or "finding",
                    payload.get("evidence_quote") or "",
                    float(payload.get("confidence") or 0.5),
                    payload.get("page_or_section") or "",
                    utc_now_iso(),
                ),
            )
        return {"claim_id": claim_id, **payload}

    def list_claims(self, *, owner: str, project_id: str | None = None) -> List[Dict[str, Any]]:
        return self._list_project_table("research_claims", owner=owner, project_id=project_id, order_col="created_at")

    def create_question(self, *, owner: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._insert_project_record(
            "research_questions",
            "question_id",
            "rq",
            owner=owner,
            project_id=payload["project_id"],
            values={
                "question": payload["question"],
                "status": payload.get("status") or "open",
                "rationale": payload.get("rationale") or "",
            },
        )

    def list_questions(self, *, owner: str, project_id: str | None = None) -> List[Dict[str, Any]]:
        return self._list_project_table("research_questions", owner=owner, project_id=project_id)

    def create_gap(self, *, owner: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._insert_project_record(
            "novelty_gaps",
            "gap_id",
            "rgap",
            owner=owner,
            project_id=payload["project_id"],
            values={
                "description": payload["description"],
                "related_sources_json": json.dumps(payload.get("related_sources") or [], ensure_ascii=False),
                "strength": payload.get("strength") or "medium",
                "risk": payload.get("risk") or "",
                "status": payload.get("status") or "open",
            },
        )

    def list_gaps(self, *, owner: str, project_id: str | None = None) -> List[Dict[str, Any]]:
        return self._list_project_table("novelty_gaps", owner=owner, project_id=project_id)

    def create_argument_node(self, *, owner: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._insert_project_record(
            "argument_nodes",
            "node_id",
            "rnode",
            owner=owner,
            project_id=payload["project_id"],
            values={
                "node_type": payload.get("node_type") or "claim",
                "label": payload["label"],
                "content": payload.get("content") or "",
                "source_id": payload.get("source_id") or "",
            },
        )

    def create_argument_edge(self, *, owner: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_project(owner=owner, project_id=payload["project_id"])
        edge_id = new_id("redge")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO argument_edges (edge_id, owner_username, project_id, from_node_id, to_node_id, relation, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge_id,
                    owner,
                    payload["project_id"],
                    payload["from_node_id"],
                    payload["to_node_id"],
                    payload.get("relation") or "supports",
                    utc_now_iso(),
                ),
            )
        return {"edge_id": edge_id, **payload}

    def argument_map(self, *, owner: str, project_id: str) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "nodes": self._list_project_table("argument_nodes", owner=owner, project_id=project_id),
            "edges": self._list_project_table("argument_edges", owner=owner, project_id=project_id, order_col="created_at"),
        }

    def _insert_project_record(
        self,
        table: str,
        id_column: str,
        id_prefix: str,
        *,
        owner: str,
        project_id: str,
        values: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._ensure_project(owner=owner, project_id=project_id)
        now = utc_now_iso()
        record_id = new_id(id_prefix)
        row = {
            id_column: record_id,
            "owner_username": owner,
            "project_id": project_id,
            **values,
            "created_at": now,
            "updated_at": now,
        }
        columns = list(row)
        placeholders = ", ".join("?" for _ in columns)
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                [row[column] for column in columns],
            )
        return row

    def _list_project_table(
        self,
        table: str,
        *,
        owner: str,
        project_id: str | None = None,
        order_col: str = "updated_at",
    ) -> List[Dict[str, Any]]:
        self.init_db()
        sql = f"SELECT * FROM {table} WHERE owner_username = ?"
        params: List[Any] = [owner]
        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        sql += f" ORDER BY {order_col} DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return self._rows(rows)
