"""SQLite cache for Market Sentinel V2 reports."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from kuro_backend.market_v2.schemas import MarketSentinelReport, market_v2_db_path


class MarketV2Cache:
    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else market_v2_db_path()
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
                CREATE TABLE IF NOT EXISTS market_v2_reports (
                    report_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    symbol TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0,
                    signal_direction TEXT NOT NULL DEFAULT '',
                    report_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_v2_reports_user ON market_v2_reports(username, workspace_id, generated_at DESC)")

    def save_report(self, report: MarketSentinelReport) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO market_v2_reports (
                    report_id, username, workspace_id, symbol, generated_at,
                    confidence, signal_direction, report_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.username,
                    report.workspace_id,
                    report.symbol,
                    report.generated_at,
                    report.confidence,
                    report.signal.direction,
                    report.model_dump_json(),
                ),
            )

    def list_reports(self, *, username: str, workspace_id: Optional[str] = None, limit: int = 20) -> List[MarketSentinelReport]:
        clauses = ["username = ?"]
        params: list[Any] = [username]
        if workspace_id:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        params.append(max(1, min(int(limit or 20), 200)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT report_json FROM market_v2_reports
                WHERE {' AND '.join(clauses)}
                ORDER BY generated_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        reports: List[MarketSentinelReport] = []
        for row in rows:
            try:
                reports.append(MarketSentinelReport.model_validate_json(row["report_json"]))
            except Exception:
                continue
        return reports

    def latest_report(self, *, username: str, symbol: str) -> Optional[MarketSentinelReport]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT report_json FROM market_v2_reports
                WHERE username = ? AND symbol = ?
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (username, symbol),
            ).fetchone()
        if not row:
            return None
        try:
            return MarketSentinelReport.model_validate_json(row["report_json"])
        except Exception:
            return None

    def health(self) -> Dict[str, Any]:
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM market_v2_reports").fetchone()[0]
        return {"db_path": str(self.db_path), "report_count": int(count)}
