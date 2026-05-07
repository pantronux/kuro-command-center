"""
Kuro finances SSoT — SQLite ledger for budgets, recurring expenses, and
daily API usage rollups (The Chancellor domain).

V1.0.0 Natural Agency audit:
- init_db() is guarded by an in-memory `_SCHEMA_READY` flag + `threading.Lock`
  so hot-path CRUD helpers never re-issue 6x CREATE TABLE IF NOT EXISTS each
  call (measured as ~40-50 fewer DDL parse/verifications per Chancellor turn).
- Indexes: `idx_recurring_active(active, label)`, `idx_watched_active(active, symbol)`
  cover the two dreaming-worker / HUD hot list queries.
- Connection policy: keep short-lived `_conn()` + WAL to avoid cross-thread
  locking; cardinality is low (budgets <= 24 rows, recurring <= ~50,
  api_usage_daily <= 365, watched_symbols <= ~30).
- `apply_watched_price` intentionally uses SELECT + UPDATE (two statements in
  one short-lived connection) to derive pct-change; SQLite RETURNING is not
  reliable on older bundled versions and the cardinality makes folding a
  non-issue.
- `format_market_snapshot_for_prompt` runs two list queries + one brief read
  per Chancellor turn; acceptable at current scale.

--- Header Doc ---
Purpose: Chancellor SSoT — budgets, recurring expenses, daily API spend,
watched stock symbols, prediction-market odds, market HUD snapshot.
Caller: main.py /api/finances/* + /api/market/*, tools/base_tools.py,
memory_coordinator (Chancellor context), dreaming_worker (fiscal + market
sentinels), observability.track_token_usage.
Dependencies: sqlite3 (WAL), stdlib (threading, datetime).
Main Functions: init_db(), upsert_budget, upsert_recurring_expense,
list_active_recurring_expenses, add_api_usage, daily_api_usage_sum,
upsert_watched_symbol, apply_watched_price, list_watched_symbols,
upsert_financial_goal, get_financial_goal, list_financial_goals,
delete_financial_goal, upsert_prediction_watch, list_prediction_watch,
set_market_brief_and_note, get_market_brief_parts, get_market_hud_items,
format_market_snapshot_for_prompt.
Side Effects: Writes to `kuro_finances.db` (WAL); one-shot schema bootstrap
guarded by `_SCHEMA_READY` + lock; logs on bootstrap + anomalies.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
logger.propagate = False

_BASE_DIR = os.path.dirname(os.path.dirname(__file__))
_DEFAULT_DB = os.path.join(_BASE_DIR, "kuro_finances.db")

# V1.0.0 Natural Agency audit:
# hot-path helpers call init_db() defensively. Running 6x CREATE TABLE IF NOT
# EXISTS + an INSERT OR IGNORE on every CRUD is wasted DDL parse/verify work.
# We short-circuit via an in-memory flag keyed by the resolved DB path so
# schema bootstrap happens exactly once per process per path (tests rotate
# the KURO_FINANCE_DB_PATH env var between tmp_paths), protected by a lock
# for thread safety.
_SCHEMA_READY_FOR: Optional[str] = None
_SCHEMA_LOCK = threading.Lock()


def _reset_schema_ready_for_tests() -> None:
    """Test hook: clear the bootstrap flag so unit tests can re-exercise init_db."""
    global _SCHEMA_READY_FOR
    with _SCHEMA_LOCK:
        _SCHEMA_READY_FOR = None


def _db_path() -> str:
    raw = os.getenv("KURO_FINANCE_DB_PATH", _DEFAULT_DB)
    return os.path.abspath(os.path.expanduser(raw))


DB_PATH = _db_path()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables if missing (idempotent + once-per-process per DB path).

    The first successful call bootstraps all six tables + indexes and
    records the resolved DB path in ``_SCHEMA_READY_FOR``. Subsequent calls
    targeting the same path short-circuit without touching SQLite.
    Thread-safe via ``_SCHEMA_LOCK``. Tests that rotate the DB path
    (monkeypatched ``KURO_FINANCE_DB_PATH``) will re-bootstrap naturally.
    """
    global _SCHEMA_READY_FOR
    current = _db_path()
    if _SCHEMA_READY_FOR == current:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY_FOR == current:
            return
        _init_db_locked()
        _SCHEMA_READY_FOR = current


def _init_db_locked() -> None:
    conn = None
    try:
        conn = _conn()
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_budget (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL DEFAULT 'Pantronux',
                month TEXT NOT NULL,
                amount_usd REAL NOT NULL,
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(username, month)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS financial_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL DEFAULT 'Pantronux',
                goal_id TEXT NOT NULL,
                name TEXT NOT NULL,
                target_amount REAL NOT NULL,
                current_amount REAL NOT NULL DEFAULT 0.0,
                deadline TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(username, goal_id)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS recurring_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL DEFAULT 'Pantronux',
                label TEXT NOT NULL,
                amount_usd REAL NOT NULL,
                cadence TEXT NOT NULL DEFAULT 'monthly',
                next_due TEXT DEFAULT '',
                category TEXT DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(username, label)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS api_usage_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL DEFAULT 'Pantronux',
                date TEXT NOT NULL,
                model_name TEXT NOT NULL DEFAULT '',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(username, date)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS watched_symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL DEFAULT 'Pantronux',
                symbol TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                baseline_price REAL,
                baseline_at TEXT,
                last_price REAL,
                last_pct_change REAL,
                last_refreshed TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(username, symbol)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS prediction_watch (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL DEFAULT 'Pantronux',
                slug TEXT NOT NULL,
                label TEXT NOT NULL,
                last_probability REAL NOT NULL DEFAULT 0.0,
                trend TEXT NOT NULL DEFAULT 'flat',
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(username, slug)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS market_hud_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL DEFAULT 'Pantronux',
                brief_text TEXT NOT NULL DEFAULT '',
                last_sentinel_note TEXT NOT NULL DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(username)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS market_sentinel_history (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                username            TEXT NOT NULL DEFAULT 'Pantronux',
                scan_timestamp      TEXT NOT NULL,
                stock_code          TEXT NOT NULL,
                company_name        TEXT NOT NULL,
                legal_name          TEXT,
                price_per_share     INTEGER NOT NULL,
                price_per_lot       INTEGER NOT NULL,
                price_category      TEXT NOT NULL,
                conclusion          TEXT NOT NULL,
                full_analysis_json  TEXT NOT NULL,
                created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS market_sentinel_stocks (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                username                 TEXT NOT NULL DEFAULT 'Pantronux',
                stock_code               TEXT NOT NULL,
                company_name             TEXT NOT NULL,
                sector                   TEXT DEFAULT '',
                current_price_per_share  INTEGER NOT NULL DEFAULT 0,
                current_price_per_lot    INTEGER NOT NULL DEFAULT 0,
                price_category           TEXT NOT NULL DEFAULT '',
                volume_24h               INTEGER NOT NULL DEFAULT 0,
                ytd_performance          REAL NOT NULL DEFAULT 0.0,
                projected_roi_1m         REAL DEFAULT NULL,
                projected_roi_1y         REAL DEFAULT NULL,
                triangulation_summary    TEXT DEFAULT '',
                conclusion               TEXT DEFAULT '',
                price_updated_at         TEXT DEFAULT NULL,
                analysis_updated_at      TEXT DEFAULT NULL,
                created_at               DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(stock_code)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS user_pinned_stocks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                pinned_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(username, stock_code)
            )
            """
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sentinel_stocks_price "
            "ON market_sentinel_stocks(current_price_per_lot ASC)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sentinel_stocks_volume "
            "ON market_sentinel_stocks(volume_24h DESC)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sentinel_stocks_roi_1m "
            "ON market_sentinel_stocks(projected_roi_1m DESC)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sentinel_stocks_roi_1y "
            "ON market_sentinel_stocks(projected_roi_1y DESC)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sentinel_code_ts "
            "ON market_sentinel_history (stock_code, scan_timestamp DESC)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sentinel_ts "
            "ON market_sentinel_history (scan_timestamp DESC)"
        )
        c.execute(
            "INSERT OR IGNORE INTO market_hud_snapshot (username, brief_text) VALUES ('Pantronux', '')"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_recurring_active_user "
            "ON recurring_expenses(active, username, label)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_watched_active_user "
            "ON watched_symbols(active, username, symbol)"
        )
        
        # Migration: Add username column to all tables if missing
        tables = [
            "monthly_budget", "financial_goals", "recurring_expenses",
            "api_usage_daily", "watched_symbols", "prediction_watch",
            "market_hud_snapshot", "market_sentinel_history",
            "market_sentinel_stocks", "user_pinned_stocks"
        ]
        for tbl in tables:
            c.execute(f"PRAGMA table_info({tbl})")
            cols = [row["name"] for row in c.fetchall()]
            if "username" not in cols:
                c.execute(f"ALTER TABLE {tbl} ADD COLUMN username TEXT NOT NULL DEFAULT 'Pantronux'")
                logger.info("[FINANCE] Added username column to %s", tbl)
        conn.commit()
        logger.info("[FINANCE] DB initialized at %s", _db_path())
    except Exception as exc:
        logger.error("[FINANCE] init failed: %s", exc)
        raise
    finally:
        if conn:
            conn.close()


def add_budget(month: str, amount_usd: float, notes: str = "", username: str = "Pantronux") -> int:
    """Insert or replace monthly budget for YYYY-MM for a specific user."""
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO monthly_budget (month, amount_usd, notes, username, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(username, month) DO UPDATE SET
                amount_usd = excluded.amount_usd,
                notes = excluded.notes,
                updated_at = datetime('now')
            """,
            (month.strip(), float(amount_usd), notes or "", username),
        )
        conn.commit()
        c.execute("SELECT id FROM monthly_budget WHERE month = ? AND username = ?", (month.strip(), username))
        row = c.fetchone()
        return int(row["id"]) if row else 0
    finally:
        conn.close()


def get_budget(month: str, username: str = "Pantronux") -> Optional[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM monthly_budget WHERE month = ? AND username = ?", (month.strip(), username))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_budgets(limit: int = 24, username: str = "Pantronux") -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM monthly_budget WHERE username = ? ORDER BY month DESC LIMIT ?",
            (username, max(1, int(limit))),
        )
        return [dict(r) for r in c.fetchall()]
    finally:
        conn.close()


def upsert_recurring_expense(
    label: str,
    amount_usd: float,
    cadence: str = "monthly",
    next_due: str = "",
    category: str = "",
    active: bool = True,
    username: str = "Pantronux",
) -> int:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO recurring_expenses
                (label, amount_usd, cadence, next_due, category, active, username, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(username, label) DO UPDATE SET
                amount_usd = excluded.amount_usd,
                cadence = excluded.cadence,
                next_due = excluded.next_due,
                category = excluded.category,
                active = excluded.active,
                updated_at = datetime('now')
            """,
            (
                label.strip(),
                float(amount_usd),
                (cadence or "monthly").strip().lower(),
                (next_due or "").strip(),
                (category or "").strip(),
                1 if active else 0,
                username,
            ),
        )
        conn.commit()
        c.execute("SELECT id FROM recurring_expenses WHERE label = ? AND username = ?", (label.strip(), username))
        row = c.fetchone()
        return int(row["id"]) if row else 0
    finally:
        conn.close()


def delete_recurring_expense(expense_id: int, username: str = "Pantronux") -> bool:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM recurring_expenses WHERE id = ? AND username = ?", (int(expense_id), username))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def list_recurring_expenses(active_only: bool = True, username: str = "Pantronux") -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        if active_only:
            c.execute(
                "SELECT * FROM recurring_expenses WHERE active = 1 AND username = ? ORDER BY label ASC",
                (username,)
            )
        else:
            c.execute("SELECT * FROM recurring_expenses WHERE username = ? ORDER BY label ASC", (username,))
        return [dict(r) for r in c.fetchall()]
    finally:
        conn.close()


def add_api_usage(
    date_str: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    username: str = "Pantronux",
) -> None:
    """Accumulate token counts and estimated cost for a calendar day for a specific user."""
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO api_usage_daily
                (date, model_name, prompt_tokens, completion_tokens,
                 total_tokens, cost_usd, username, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(username, date) DO UPDATE SET
                prompt_tokens = api_usage_daily.prompt_tokens + excluded.prompt_tokens,
                completion_tokens = api_usage_daily.completion_tokens + excluded.completion_tokens,
                total_tokens = api_usage_daily.total_tokens + excluded.total_tokens,
                cost_usd = api_usage_daily.cost_usd + excluded.cost_usd,
                model_name = excluded.model_name,
                updated_at = datetime('now')
            """,
            (
                date_str.strip(),
                (model_name or "").strip(),
                int(prompt_tokens),
                int(completion_tokens),
                int(prompt_tokens) + int(completion_tokens),
                float(cost_usd),
                username,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_daily_api_cost_usd(date_str: str, username: str = "Pantronux") -> float:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT cost_usd FROM api_usage_daily WHERE date = ? AND username = ?",
            (date_str.strip(), username),
        )
        row = c.fetchone()
        return float(row["cost_usd"]) if row else 0.0
    finally:
        conn.close()


def upsert_watched_symbol(symbol: str, label: str = "", username: str = "Pantronux") -> None:
    """Add or reactivate a watched ticker for a specific user."""
    init_db()
    sym = (symbol or "").strip().upper()
    if not sym:
        raise ValueError("symbol required")
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO watched_symbols (symbol, label, username, active, updated_at)
            VALUES (?, ?, ?, 1, datetime('now'))
            ON CONFLICT(username, symbol) DO UPDATE SET
                label = COALESCE(NULLIF(excluded.label, ''), watched_symbols.label),
                active = 1,
                updated_at = datetime('now')
            """,
            (sym, (label or "").strip(), username),
        )
        conn.commit()
    finally:
        conn.close()


def delete_watched_symbol(symbol: str, username: str = "Pantronux") -> bool:
    init_db()
    sym = (symbol or "").strip().upper()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM watched_symbols WHERE symbol = ? AND username = ?", (sym, username))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def get_watched_symbol(symbol: str, username: str = "Pantronux") -> Optional[Dict[str, Any]]:
    init_db()
    sym = (symbol or "").strip().upper()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM watched_symbols WHERE symbol = ? AND username = ?", (sym, username))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_watched_symbols(active_only: bool = True, username: str = "Pantronux") -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        if active_only:
            c.execute(
                "SELECT * FROM watched_symbols WHERE active = 1 AND username = ? ORDER BY symbol ASC",
                (username,)
            )
        else:
            c.execute("SELECT * FROM watched_symbols WHERE username = ? ORDER BY symbol ASC", (username,))
        return [dict(r) for r in c.fetchall()]
    finally:
        conn.close()


def apply_watched_price(symbol: str, new_price: float, username: str = "Pantronux") -> Dict[str, Any]:
    """Update last close for a watched symbol for a specific user."""
    init_db()
    sym = (symbol or "").strip().upper()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("BEGIN IMMEDIATE")
        c.execute("SELECT * FROM watched_symbols WHERE symbol = ? AND username = ?", (sym, username))
        row = c.fetchone()
        if not row:
            return {}
        d = dict(row)
        pct = 0.0
        if d.get("baseline_price") is None:
            c.execute(
                """
                UPDATE watched_symbols SET
                    baseline_price = ?,
                    baseline_at = datetime('now'),
                    last_price = ?,
                    last_pct_change = 0,
                    last_refreshed = datetime('now'),
                    updated_at = datetime('now')
                WHERE symbol = ? AND username = ?
                """,
                (float(new_price), float(new_price), sym, username),
            )
        else:
            old = d.get("last_price")
            if old is not None:
                oldf = float(old)
                if oldf != 0.0:
                    pct = (float(new_price) - oldf) / oldf * 100.0
            c.execute(
                """
                UPDATE watched_symbols SET
                    last_price = ?,
                    last_pct_change = ?,
                    last_refreshed = datetime('now'),
                    updated_at = datetime('now')
                WHERE symbol = ? AND username = ?
                """,
                (float(new_price), float(pct), sym, username),
            )
        conn.commit()
        return {"symbol": sym, "last_price": float(new_price), "last_pct_change": float(pct)}
    finally:
        conn.close()


def upsert_financial_goal(
    goal_id: str,
    name: str,
    target_amount: float,
    current_amount: float = 0.0,
    deadline: Optional[str] = None,
    username: str = "Pantronux",
) -> None:
    """Insert or replace a financial goal for a specific user."""
    init_db()
    gid = (goal_id or "").strip()
    if not gid:
        raise ValueError("goal_id required")
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO financial_goals
                (goal_id, name, target_amount, current_amount, deadline, username, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(username, goal_id) DO UPDATE SET
                name = excluded.name,
                target_amount = excluded.target_amount,
                current_amount = excluded.current_amount,
                deadline = excluded.deadline,
                updated_at = datetime('now')
            """,
            (
                gid,
                (name or gid).strip(),
                float(target_amount),
                float(current_amount),
                (deadline or "").strip() or None,
                username,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_financial_goal(goal_id: str, username: str = "Pantronux") -> Optional[Dict[str, Any]]:
    init_db()
    gid = (goal_id or "").strip()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM financial_goals WHERE goal_id = ? AND username = ?", (gid, username))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_financial_goals(username: str = "Pantronux") -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM financial_goals WHERE username = ? ORDER BY created_at DESC", (username,))
        return [dict(r) for r in c.fetchall()]
    finally:
        conn.close()


def delete_financial_goal(goal_id: str, username: str = "Pantronux") -> bool:
    init_db()
    gid = (goal_id or "").strip()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM financial_goals WHERE goal_id = ? AND username = ?", (gid, username))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def upsert_prediction_watch(
    slug: str,
    label: str,
    probability: float,
    trend: str = "flat",
    username: str = "Pantronux",
) -> None:
    init_db()
    sl = (slug or "").strip()
    if not sl:
        raise ValueError("slug required")
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO prediction_watch (slug, label, last_probability, trend, username, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(username, slug) DO UPDATE SET
                label = excluded.label,
                last_probability = excluded.last_probability,
                trend = excluded.trend,
                updated_at = datetime('now')
            """,
            (sl, (label or sl).strip(), float(probability), (trend or "flat").strip().lower()[:16], username),
        )
        conn.commit()
    finally:
        conn.close()


def list_prediction_watch(username: str = "Pantronux") -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM prediction_watch WHERE username = ? ORDER BY slug ASC", (username,))
        return [dict(r) for r in c.fetchall()]
    finally:
        conn.close()


def delete_prediction_watch(slug: str, username: str = "Pantronux") -> bool:
    init_db()
    sl = (slug or "").strip()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM prediction_watch WHERE slug = ? AND username = ?", (sl, username))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def set_market_brief_and_note(brief_text: str, sentinel_note: str = "", username: str = "Pantronux") -> None:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO market_hud_snapshot (username, brief_text, last_sentinel_note, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(username) DO UPDATE SET
                brief_text = excluded.brief_text,
                last_sentinel_note = excluded.last_sentinel_note,
                updated_at = datetime('now')
            """,
            (username, brief_text or "", sentinel_note or ""),
        )
        conn.commit()
    finally:
        conn.close()


def get_market_brief_parts(username: str = "Pantronux") -> Dict[str, str]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT brief_text, last_sentinel_note FROM market_hud_snapshot WHERE username = ?",
            (username,)
        )
        row = c.fetchone()
        if not row:
            return {"brief_text": "", "last_sentinel_note": ""}
        return {
            "brief_text": str(row["brief_text"] or ""),
            "last_sentinel_note": str(row["last_sentinel_note"] or ""),
        }
    finally:
        conn.close()


def _trend_arrow(pct: Optional[float]) -> str:
    if pct is None:
        return "flat"
    if pct > 0.05:
        return "up"
    if pct < -0.05:
        return "down"
    return "flat"


def _equity_sentiment(pct: Optional[float]) -> str:
    if pct is None:
        return "FLAT"
    if pct >= 1.0:
        return "BULLISH"
    if pct <= -1.0:
        return "BEARISH"
    return "FLAT"


def get_market_hud_items(username: str = "Pantronux") -> List[Dict[str, Any]]:
    """Compose HUD chips for /api/market/hud for a specific user."""
    items: List[Dict[str, Any]] = []
    for p in list_prediction_watch(username=username):
        prob = float(p.get("last_probability") or 0.0)
        items.append(
            {
                "id": p["slug"],
                "label": p.get("label") or p["slug"],
                "prob": round(prob * 100.0, 1) if prob <= 1.0 else round(prob, 1),
                "trend": (p.get("trend") or "flat").lower(),
                "sentiment": None,
                "kind": "prediction",
            }
        )
    for w in list_watched_symbols(active_only=True, username=username):
        sym = w["symbol"]
        pct = w.get("last_pct_change")
        pf = float(pct) if pct is not None else None
        items.append(
            {
                "id": sym,
                "label": (w.get("label") or sym).strip() or sym,
                "prob": None,
                "trend": _trend_arrow(pf),
                "sentiment": _equity_sentiment(pf),
                "kind": "equity",
                "last_pct_change": pf,
            }
        )
    return items


def format_market_snapshot_for_prompt(username: str = "Pantronux") -> str:
    """Cached market / watchlist block for Chancellor for a specific user."""
    try:
        lines = ["[MARKET CACHE — temporary facts from ledger; verify via tools if live quote needed]"]
        ws = list_watched_symbols(active_only=True, username=username)
        if ws:
            lines.append("- Watched symbols:")
            for w in ws[:24]:
                lp = w.get("last_price")
                pct = w.get("last_pct_change")
                ref = w.get("last_refreshed") or ""
                lines.append(
                    f"  • {w['symbol']}: last={lp} USD chg={pct}% (refreshed {ref})"
                )
        else:
            lines.append("- Watched symbols: none")
        pw = list_prediction_watch(username=username)
        if pw:
            lines.append("- Prediction watch (cached):")
            for p in pw[:16]:
                lines.append(
                    f"  • {p['slug']}: {p.get('label', '')} "
                    f"p={float(p.get('last_probability') or 0):.3f} trend={p.get('trend', '')}"
                )
        parts = get_market_brief_parts(username=username)
        if parts.get("last_sentinel_note"):
            lines.append(f"- Last sentinel note: {parts['last_sentinel_note']}")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("[FINANCE] market snapshot failed for %s: %s", username, exc)
        return "[MARKET CACHE — unavailable]"


def get_last_n_days_spend(n: int = 7, username: str = "Pantronux") -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT date, model_name, prompt_tokens, completion_tokens,
                   total_tokens, cost_usd, updated_at
            FROM api_usage_daily
            WHERE username = ?
            ORDER BY date DESC
            LIMIT ?
            """,
            (username, max(1, int(n))),
        )
        return [dict(r) for r in c.fetchall()]
    finally:
        conn.close()


def insert_sentinel_scan(username: str, scan_timestamp: str, stocks: list[dict]) -> bool:
    """Insert a batch of stock scan results into history."""
    conn = None
    try:
        conn = _conn()
        c = conn.cursor()
        for s in stocks:
            c.execute(
                """
                INSERT INTO market_sentinel_history (
                    username, scan_timestamp, stock_code, company_name, legal_name,
                    price_per_share, price_per_lot, price_category, conclusion, full_analysis_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username, scan_timestamp, s["stock_code"], s["company_name"], s.get("legal_name"),
                    s["current_price_per_share"], s["current_price_per_lot"], s["price_category"],
                    s["conclusion"], json.dumps(s)
                )
            )
        conn.commit()
        return True
    except Exception as exc:
        logger.error("[FINANCE] insert_sentinel_scan failed: %s", exc)
        return False
    finally:
        if conn:
            conn.close()


def get_sentinel_latest_per_stock(username: str = "Pantronux", hours: int = 24) -> list[dict]:
    """Get the latest unique scan result for each stock code within the last N hours."""
    conn = None
    try:
        conn = _conn()
        # Using a subquery to find the max(id) for each stock_code to get the absolute latest
        # within the time window.
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        cursor = conn.execute(
            """
            SELECT * FROM market_sentinel_history 
            WHERE username = ? AND scan_timestamp >= ?
            GROUP BY stock_code
            HAVING id = MAX(id)
            ORDER BY price_category ASC, stock_code ASC
            """,
            (username, since)
        )
        return [json.loads(row["full_analysis_json"]) for row in cursor.fetchall()]
    except Exception as exc:
        logger.error("[FINANCE] get_sentinel_latest_per_stock failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


def get_sentinel_history_for_chart(stock_code: str, username: str = "Pantronux", days: int = 7) -> list[dict]:
    """Get price history for a specific stock for charting."""
    conn = None
    try:
        conn = _conn()
        since = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = conn.execute(
            """
            SELECT scan_timestamp, price_per_share, price_per_lot
            FROM market_sentinel_history
            WHERE username = ? AND stock_code = ? AND scan_timestamp >= ?
            ORDER BY scan_timestamp ASC
            """,
            (username, stock_code, since)
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as exc:
        logger.error("[FINANCE] get_sentinel_history_for_chart failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


def get_sentinel_latest_summary(username: str = "Pantronux", limit: int = 10) -> list[dict]:
    """Get the latest scan results (unfiltered by stock_code uniqueness) for overview."""
    conn = None
    try:
        conn = _conn()
        cursor = conn.execute(
            """
            SELECT * FROM market_sentinel_history
            WHERE username = ?
            ORDER BY scan_timestamp DESC, id DESC
            LIMIT ?
            """,
            (username, limit)
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as exc:
        logger.error("[FINANCE] get_sentinel_latest_summary failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


def format_ledger_snapshot(username: str = "Pantronux") -> str:
    """Compact block for Chancellor prompt injection for a specific user."""
    try:
        today = date.today()
        month_key = today.strftime("%Y-%m")
        bud = get_budget(month_key, username=username)
        exps = list_recurring_expenses(active_only=True, username=username)
        usage = get_last_n_days_spend(7, username=username)
        lines = ["[FINANCES SSoT — ledger snapshot]"]
        if bud:
            lines.append(
                f"- Monthly budget ({month_key}): USD {float(bud['amount_usd']):.2f}"
                + (f" — {bud.get('notes', '')}" if bud.get("notes") else "")
            )
        else:
            lines.append(f"- Monthly budget ({month_key}): not yet recorded in SSoT")
        if exps:
            lines.append("- Recurring obligations:")
            for e in exps[:20]:
                lines.append(
                    f"  • {e['label']}: USD {float(e['amount_usd']):.2f} "
                    f"({e.get('cadence', 'monthly')}), next: {e.get('next_due', '')}"
                )
        else:
            lines.append("- Recurring obligations: none recorded")
        if usage:
            lines.append("- Recent API usage (ledger):")
            for u in usage[:7]:
                lines.append(
                    f"  • {u['date']}: USD {float(u['cost_usd']):.4f} "
                    f"({u.get('total_tokens', 0)} tokens)"
                )
        else:
            lines.append("- Recent API usage: no rows yet")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("[FINANCE] snapshot failed: %s", exc)
        return "[FINANCES SSoT — ledger unavailable]"


def upsert_sentinel_stock_price(stock_code, company_name, sector,
                               price_per_share, price_per_lot, price_category,
                               volume_24h, ytd_performance, username="Pantronux") -> bool:
    """Upsert price and volume from yfinance. Does NOT touch LLM analysis columns."""
    conn = None
    try:
        conn = _conn()
        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO market_sentinel_stocks (
                username, stock_code, company_name, sector,
                current_price_per_share, current_price_per_lot, price_category,
                volume_24h, ytd_performance, price_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_code) DO UPDATE SET
                current_price_per_share = excluded.current_price_per_share,
                current_price_per_lot = excluded.current_price_per_lot,
                price_category = excluded.price_category,
                volume_24h = excluded.volume_24h,
                ytd_performance = excluded.ytd_performance,
                price_updated_at = excluded.price_updated_at
            """,
            (username, stock_code, company_name, sector, 
             price_per_share, price_per_lot, price_category,
             volume_24h, ytd_performance, now)
        )
        conn.commit()
        return True
    except Exception as exc:
        logger.error("[FINANCE] upsert_sentinel_stock_price failed: %s", exc)
        return False
    finally:
        if conn:
            conn.close()


def update_sentinel_stock_analysis(stock_code, projected_roi_1m, projected_roi_1y,
                                  triangulation_summary, conclusion, username="Pantronux") -> bool:
    """Update only LLM-generated columns (ROI, summary, conclusion)."""
    conn = None
    try:
        conn = _conn()
        now = datetime.now().isoformat()
        conn.execute(
            """
            UPDATE market_sentinel_stocks SET
                projected_roi_1m = ?,
                projected_roi_1y = ?,
                triangulation_summary = ?,
                conclusion = ?,
                analysis_updated_at = ?
            WHERE stock_code = ?
            """,
            (projected_roi_1m, projected_roi_1y, triangulation_summary, conclusion, now, stock_code)
        )
        conn.commit()
        return True
    except Exception as exc:
        logger.error("[FINANCE] update_sentinel_stock_analysis failed: %s", exc)
        return False
    finally:
        if conn:
            conn.close()


def get_all_sentinel_stocks(sort_by="latest", category=None, username="Pantronux") -> list[dict]:
    """Fetch all stocks with sorting and optional category filtering."""
    conn = None
    try:
        conn = _conn()
        query = "SELECT * FROM market_sentinel_stocks WHERE username = ?"
        params = [username]
        
        if category:
            query += " AND price_category = ?"
            params.append(category)
            
        # Sorting logic
        if sort_by == "latest":
            query += " ORDER BY price_updated_at DESC"
        elif sort_by == "oldest":
            query += " ORDER BY price_updated_at ASC"
        elif sort_by == "price_asc":
            query += " ORDER BY current_price_per_lot ASC"
        elif sort_by == "price_desc":
            query += " ORDER BY current_price_per_lot DESC"
        elif sort_by == "volume":
            query += " ORDER BY volume_24h DESC"
        elif sort_by == "roi_1m":
            query += " ORDER BY projected_roi_1m DESC"
        elif sort_by == "roi_1y":
            query += " ORDER BY projected_roi_1y DESC"
            
        cursor = conn.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]
    except Exception as exc:
        logger.error("[FINANCE] get_all_sentinel_stocks failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


def get_sentinel_stock_detail(stock_code, username="Pantronux") -> dict | None:
    """Fetch a single stock by code."""
    conn = None
    try:
        conn = _conn()
        cursor = conn.execute("SELECT * FROM market_sentinel_stocks WHERE stock_code = ?", (stock_code,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as exc:
        logger.error("[FINANCE] get_sentinel_stock_detail failed: %s", exc)
        return None
    finally:
        if conn:
            conn.close()


def toggle_pin_stock(username, stock_code) -> dict:
    """Toggle pin/unpin status. Max 3 pins per user."""
    conn = None
    try:
        conn = _conn()
        # Check current pin status
        cursor = conn.execute(
            "SELECT id FROM user_pinned_stocks WHERE username = ? AND stock_code = ?",
            (username, stock_code)
        )
        existing = cursor.fetchone()
        
        if existing:
            conn.execute("DELETE FROM user_pinned_stocks WHERE id = ?", (existing["id"],))
            conn.commit()
            return {"action": "unpinned", "count": count_user_pins(username)}
        else:
            # Check pin count limit
            if count_user_pins(username) >= 3:
                raise ValueError("Maksimal 3 pin diperbolehkan per user.")
            
            conn.execute(
                "INSERT INTO user_pinned_stocks (username, stock_code) VALUES (?, ?)",
                (username, stock_code)
            )
            conn.commit()
            return {"action": "pinned", "count": count_user_pins(username)}
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise exc
        logger.error("[FINANCE] toggle_pin_stock failed: %s", exc)
        return {"action": "error", "message": str(exc)}
    finally:
        if conn:
            conn.close()


def get_user_pins(username) -> list[str]:
    """Return list of stock_codes pinned by the user."""
    conn = None
    try:
        conn = _conn()
        cursor = conn.execute("SELECT stock_code FROM user_pinned_stocks WHERE username = ?", (username,))
        return [r["stock_code"] for r in cursor.fetchall()]
    except Exception as exc:
        logger.error("[FINANCE] get_user_pins failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


def count_user_pins(username) -> int:
    """Return count of pins for a user."""
    conn = None
    try:
        conn = _conn()
        cursor = conn.execute("SELECT COUNT(*) FROM user_pinned_stocks WHERE username = ?", (username,))
        return cursor.fetchone()[0]
    except Exception as exc:
        logger.error("[FINANCE] count_user_pins failed: %s", exc)
        return 0
    finally:
        if conn:
            conn.close()


__all__ = [
    "DB_PATH",
    "init_db",
    "add_budget",
    "get_budget",
    "list_budgets",
    "upsert_recurring_expense",
    "delete_recurring_expense",
    "list_recurring_expenses",
    "add_api_usage",
    "get_daily_api_cost_usd",
    "get_last_n_days_spend",
    "format_ledger_snapshot",
    "upsert_watched_symbol",
    "delete_watched_symbol",
    "get_watched_symbol",
    "list_watched_symbols",
    "apply_watched_price",
    "upsert_financial_goal",
    "get_financial_goal",
    "list_financial_goals",
    "delete_financial_goal",
    "upsert_prediction_watch",
    "list_prediction_watch",
    "delete_prediction_watch",
    "set_market_brief_and_note",
    "get_market_brief_parts",
    "get_market_hud_items",
    "format_market_snapshot_for_prompt",
    "insert_sentinel_scan",
    "get_sentinel_latest_per_stock",
    "get_sentinel_history_for_chart",
    "get_sentinel_latest_summary",
    "upsert_sentinel_stock_price",
    "update_sentinel_stock_analysis",
    "get_all_sentinel_stocks",
    "get_sentinel_stock_detail",
    "toggle_pin_stock",
    "get_user_pins",
    "count_user_pins",
]
