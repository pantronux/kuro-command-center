"""Kuro-native Deep Research V2 job lifecycle."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from kuro_backend.tools_v2.audit import utc_now_iso
from kuro_backend.tools_v2.schemas import DeepResearchJob, NormalizedSource, tools_v2_db_path
from kuro_backend.tools_v2.web_search import WebSearchV2


class DeepResearchStore:
    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else tools_v2_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deep_research_jobs_v2 (
                    job_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    query TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_json TEXT NOT NULL DEFAULT '{}',
                    sources_json TEXT NOT NULL DEFAULT '[]',
                    reliability_json TEXT NOT NULL DEFAULT '[]',
                    report_markdown TEXT NOT NULL DEFAULT '',
                    exportable_report_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_deep_research_v2_user ON deep_research_jobs_v2(username, workspace_id, created_at)")

    def create_job(self, *, username: str, workspace_id: str, query: str) -> DeepResearchJob:
        now = utc_now_iso()
        job_id = f"dr_{uuid.uuid4().hex}"
        plan = self.build_plan(query)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO deep_research_jobs_v2 (
                    job_id, username, workspace_id, query, status, plan_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (
                    job_id,
                    username,
                    workspace_id or "default",
                    query.strip(),
                    json.dumps(plan, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
        job = self.get_job(job_id=job_id, username=username)
        if job is None:
            raise RuntimeError("deep research job was not persisted")
        return job

    def get_job(self, *, job_id: str, username: str) -> Optional[DeepResearchJob]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM deep_research_jobs_v2 WHERE job_id = ? AND username = ?",
                (job_id, username),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, *, username: str, workspace_id: Optional[str] = None, limit: int = 50) -> List[DeepResearchJob]:
        clauses = ["username = ?"]
        params: list[Any] = [username]
        if workspace_id:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        params.append(max(1, min(int(limit or 50), 200)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM deep_research_jobs_v2
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def mark_running(self, *, job_id: str) -> None:
        self._update(job_id=job_id, status="running")

    def complete_job(
        self,
        *,
        job_id: str,
        sources: List[NormalizedSource],
        reliability_scores: List[Dict[str, Any]],
        report_markdown: str,
        exportable_report: Dict[str, Any],
    ) -> None:
        self._update(
            job_id=job_id,
            status="completed",
            sources_json=json.dumps([source.model_dump() for source in sources], ensure_ascii=False, sort_keys=True),
            reliability_json=json.dumps(reliability_scores, ensure_ascii=False, sort_keys=True),
            report_markdown=report_markdown,
            exportable_report_json=json.dumps(exportable_report, ensure_ascii=False, sort_keys=True),
            error="",
        )

    def fail_job(self, *, job_id: str, error: str) -> None:
        self._update(job_id=job_id, status="failed", error=str(error or "")[:2000])

    def build_plan(self, query: str) -> Dict[str, Any]:
        return {
            "query": query.strip(),
            "steps": [
                "clarify_research_question",
                "collect_sources",
                "score_source_reliability",
                "synthesize_with_citations",
                "prepare_exportable_report",
            ],
        }

    def _update(self, *, job_id: str, status: str, **fields: Any) -> None:
        assignments = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, utc_now_iso()]
        for field_name, value in fields.items():
            assignments.append(f"{field_name} = ?")
            params.append(value)
        params.append(job_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE deep_research_jobs_v2 SET {', '.join(assignments)} WHERE job_id = ?",
                tuple(params),
            )

    def _row_to_job(self, row: sqlite3.Row) -> DeepResearchJob:
        def _loads(value: str, fallback: Any) -> Any:
            try:
                parsed = json.loads(value or "")
                return parsed
            except Exception:
                return fallback

        sources_raw = _loads(row["sources_json"], [])
        sources = [NormalizedSource(**item) for item in sources_raw if isinstance(item, dict)]
        return DeepResearchJob(
            job_id=row["job_id"],
            username=row["username"],
            workspace_id=row["workspace_id"],
            query=row["query"],
            status=row["status"],
            plan=_loads(row["plan_json"], {}),
            sources=sources,
            reliability_scores=_loads(row["reliability_json"], []),
            report_markdown=row["report_markdown"],
            exportable_report=_loads(row["exportable_report_json"], {}),
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class DeepResearchService:
    def __init__(
        self,
        *,
        store: Optional[DeepResearchStore] = None,
        web_search: Optional[WebSearchV2] = None,
    ) -> None:
        self.store = store or DeepResearchStore()
        self.web_search = web_search or WebSearchV2()

    def create_job(self, *, username: str, workspace_id: str, query: str) -> DeepResearchJob:
        return self.store.create_job(username=username, workspace_id=workspace_id, query=query)

    def run_job(self, job_id: str) -> Optional[DeepResearchJob]:
        job = self._get_by_id_any_user(job_id)
        if job is None:
            return None
        self.store.mark_running(job_id=job_id)
        try:
            search_result = self.web_search.search(query=job.query, search_type="search", max_results=5)
            sources = [
                NormalizedSource(**item)
                for item in (search_result.get("sources") or [])
                if isinstance(item, dict)
            ]
            reliability = [self.score_source(source) for source in sources]
            report = self.synthesize_report(query=job.query, sources=sources, reliability_scores=reliability)
            exportable_report = {
                "format": "markdown",
                "query": job.query,
                "source_count": len(sources),
                "report_markdown": report,
                "provenance": [source.model_dump() for source in sources],
            }
            self.store.complete_job(
                job_id=job_id,
                sources=sources,
                reliability_scores=reliability,
                report_markdown=report,
                exportable_report=exportable_report,
            )
        except Exception as exc:
            self.store.fail_job(job_id=job_id, error=str(exc))
        return self.store.get_job(job_id=job_id, username=job.username)

    def get_job(self, *, job_id: str, username: str) -> Optional[DeepResearchJob]:
        return self.store.get_job(job_id=job_id, username=username)

    def list_jobs(self, *, username: str, workspace_id: Optional[str] = None, limit: int = 50) -> List[DeepResearchJob]:
        return self.store.list_jobs(username=username, workspace_id=workspace_id, limit=limit)

    def score_source(self, source: NormalizedSource) -> Dict[str, Any]:
        parsed = urlparse(source.url)
        host = parsed.netloc.lower()
        score = source.confidence or 0.5
        if host.endswith(".gov") or ".gov." in host:
            score = max(score, 0.86)
        elif host.endswith(".edu") or ".edu." in host:
            score = max(score, 0.82)
        elif host:
            score = max(score, 0.68)
        return {
            "url": source.url,
            "domain": host,
            "score": round(min(score, 1.0), 2),
            "signals": {
                "has_url": bool(source.url),
                "has_snippet": bool(source.snippet),
                "source_type": source.source_type,
            },
        }

    def synthesize_report(
        self,
        *,
        query: str,
        sources: List[NormalizedSource],
        reliability_scores: List[Dict[str, Any]],
    ) -> str:
        if not sources:
            return (
                f"# Deep Research Report\n\nQuery: {query}\n\n"
                "Result: insufficient evidence. No configured search source returned grounded citations.\n"
            )
        lines = [
            "# Deep Research Report",
            "",
            f"Query: {query}",
            "",
            "## Summary",
            f"Collected {len(sources)} source(s). The synthesis is limited to the cited source snippets below.",
            "",
            "## Evidence",
        ]
        scores_by_url = {item.get("url"): item.get("score") for item in reliability_scores}
        for idx, source in enumerate(sources, start=1):
            score = scores_by_url.get(source.url, source.confidence)
            lines.append(f"{idx}. {source.title or source.url} ({source.url}) - reliability {score}")
            if source.snippet:
                lines.append(f"   {source.snippet}")
        lines.extend(["", "## Provenance", "All claims above are grounded only in the listed sources."])
        return "\n".join(lines)

    def _get_by_id_any_user(self, job_id: str) -> Optional[DeepResearchJob]:
        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT * FROM deep_research_jobs_v2 WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self.store._row_to_job(row) if row else None
