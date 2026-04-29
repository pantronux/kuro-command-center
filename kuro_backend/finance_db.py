"""
Kuro finances SSoT — SQLite ledger for budgets, recurring expenses, and
daily API usage rollups (The Chancellor domain).

V7.2.1 Natural Agency audit:
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

import logging
import os
import sqlite3
import threading
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
logger.propagate = False

_BASE_DIR = os.path.dirname(os.path.dirname(__file__))
_DEFAULT_DB = os.path.join(_BASE_DIR, "kuro_finances.db")

# V7.2.1 Natural Agency audit:
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
                month TEXT NOT NULL UNIQUE,
                amount_usd REAL NOT NULL,
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS financial_goals (
                goal_id TEXT PRIMARY KEY NOT NULL,
                name TEXT NOT NULL,
                target_amount REAL NOT NULL,
                current_amount REAL NOT NULL DEFAULT 0.0,
                deadline TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS recurring_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL UNIQUE,
                amount_usd REAL NOT NULL,
                cadence TEXT NOT NULL DEFAULT 'monthly',
                next_due TEXT DEFAULT '',
                category TEXT DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS api_usage_daily (
                date TEXT PRIMARY KEY NOT NULL,
                model_name TEXT NOT NULL DEFAULT '',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS watched_symbols (
                symbol TEXT PRIMARY KEY NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                baseline_price REAL,
                baseline_at TEXT,
                last_price REAL,
                last_pct_change REAL,
                last_refreshed TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS prediction_watch (
                slug TEXT PRIMARY KEY NOT NULL,
                label TEXT NOT NULL,
                last_probability REAL NOT NULL DEFAULT 0.0,
                trend TEXT NOT NULL DEFAULT 'flat',
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS market_hud_snapshot (
                id INTEGER PRIMARY KEY NOT NULL DEFAULT 1 CHECK (id = 1),
                brief_text TEXT NOT NULL DEFAULT '',
                last_sentinel_note TEXT NOT NULL DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        c.execute(
            "INSERT OR IGNORE INTO market_hud_snapshot (id, brief_text) VALUES (1, '')"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_recurring_active "
            "ON recurring_expenses(active, label)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_watched_active "
            "ON watched_symbols(active, symbol)"
        )
        conn.commit()
        logger.info("[FINANCE] DB initialized at %s", _db_path())
    except Exception as exc:
        logger.error("[FINANCE] init failed: %s", exc)
        raise
    finally:
        if conn:
            conn.close()


def add_budget(month: str, amount_usd: float, notes: str = "") -> int:
    """Insert or replace monthly budget for YYYY-MM."""
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO monthly_budget (month, amount_usd, notes, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(month) DO UPDATE SET
                amount_usd = excluded.amount_usd,
                notes = excluded.notes,
                updated_at = datetime('now')
            """,
            (month.strip(), float(amount_usd), notes or ""),
        )
        conn.commit()
        c.execute("SELECT id FROM monthly_budget WHERE month = ?", (month.strip(),))
        row = c.fetchone()
        return int(row["id"]) if row else 0
    finally:
        conn.close()


def get_budget(month: str) -> Optional[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM monthly_budget WHERE month = ?", (month.strip(),))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_budgets(limit: int = 24) -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM monthly_budget ORDER BY month DESC LIMIT ?",
            (max(1, int(limit)),),
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
) -> int:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO recurring_expenses
                (label, amount_usd, cadence, next_due, category, active, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(label) DO UPDATE SET
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
            ),
        )
        conn.commit()
        c.execute("SELECT id FROM recurring_expenses WHERE label = ?", (label.strip(),))
        row = c.fetchone()
        return int(row["id"]) if row else 0
    finally:
        conn.close()


def delete_recurring_expense(expense_id: int) -> bool:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM recurring_expenses WHERE id = ?", (int(expense_id),))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def list_recurring_expenses(active_only: bool = True) -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        if active_only:
            c.execute(
                "SELECT * FROM recurring_expenses WHERE active = 1 ORDER BY label ASC"
            )
        else:
            c.execute("SELECT * FROM recurring_expenses ORDER BY label ASC")
        return [dict(r) for r in c.fetchall()]
    finally:
        conn.close()


def add_api_usage(
    date_str: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
) -> None:
    """Accumulate token counts and estimated cost for a calendar day."""
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO api_usage_daily
                (date, model_name, prompt_tokens, completion_tokens,
                 total_tokens, cost_usd, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(date) DO UPDATE SET
                prompt_tokens = prompt_tokens + excluded.prompt_tokens,
                completion_tokens = completion_tokens + excluded.completion_tokens,
                total_tokens = total_tokens + excluded.total_tokens,
                cost_usd = cost_usd + excluded.cost_usd,
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
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_daily_api_cost_usd(date_str: str) -> float:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT cost_usd FROM api_usage_daily WHERE date = ?",
            (date_str.strip(),),
        )
        row = c.fetchone()
        return float(row["cost_usd"]) if row else 0.0
    finally:
        conn.close()


def upsert_watched_symbol(symbol: str, label: str = "") -> None:
    """Add or reactivate a watched ticker (US symbols via OpenClaw/Stooq .us)."""
    init_db()
    sym = (symbol or "").strip().upper()
    if not sym:
        raise ValueError("symbol required")
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO watched_symbols (symbol, label, active, updated_at)
            VALUES (?, ?, 1, datetime('now'))
            ON CONFLICT(symbol) DO UPDATE SET
                label = COALESCE(NULLIF(excluded.label, ''), watched_symbols.label),
                active = 1,
                updated_at = datetime('now')
            """,
            (sym, (label or "").strip()),
        )
        conn.commit()
    finally:
        conn.close()


def delete_watched_symbol(symbol: str) -> bool:
    init_db()
    sym = (symbol or "").strip().upper()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM watched_symbols WHERE symbol = ?", (sym,))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def get_watched_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    init_db()
    sym = (symbol or "").strip().upper()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM watched_symbols WHERE symbol = ?", (sym,))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_watched_symbols(active_only: bool = True) -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        if active_only:
            c.execute(
                "SELECT * FROM watched_symbols WHERE active = 1 ORDER BY symbol ASC"
            )
        else:
            c.execute("SELECT * FROM watched_symbols ORDER BY symbol ASC")
        return [dict(r) for r in c.fetchall()]
    finally:
        conn.close()


def apply_watched_price(symbol: str, new_price: float) -> Dict[str, Any]:
    """Update last close for a watched symbol; set baseline on first tick. Returns pct vs prior last."""
    init_db()
    sym = (symbol or "").strip().upper()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM watched_symbols WHERE symbol = ?", (sym,))
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
                WHERE symbol = ?
                """,
                (float(new_price), float(new_price), sym),
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
                WHERE symbol = ?
                """,
                (float(new_price), float(pct), sym),
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
) -> None:
    """Insert or replace a financial goal (e.g. 'Emergency Fund')."""
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
                (goal_id, name, target_amount, current_amount, deadline, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(goal_id) DO UPDATE SET
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
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_financial_goal(goal_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    gid = (goal_id or "").strip()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM financial_goals WHERE goal_id = ?", (gid,))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_financial_goals() -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM financial_goals ORDER BY created_at DESC")
        return [dict(r) for r in c.fetchall()]
    finally:
        conn.close()


def delete_financial_goal(goal_id: str) -> bool:
    init_db()
    gid = (goal_id or "").strip()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM financial_goals WHERE goal_id = ?", (gid,))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def upsert_prediction_watch(
    slug: str,
    label: str,
    probability: float,
    trend: str = "flat",
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
            INSERT INTO prediction_watch (slug, label, last_probability, trend, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(slug) DO UPDATE SET
                label = excluded.label,
                last_probability = excluded.last_probability,
                trend = excluded.trend,
                updated_at = datetime('now')
            """,
            (sl, (label or sl).strip(), float(probability), (trend or "flat").strip().lower()[:16]),
        )
        conn.commit()
    finally:
        conn.close()


def list_prediction_watch() -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM prediction_watch ORDER BY slug ASC")
        return [dict(r) for r in c.fetchall()]
    finally:
        conn.close()


def delete_prediction_watch(slug: str) -> bool:
    init_db()
    sl = (slug or "").strip()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM prediction_watch WHERE slug = ?", (sl,))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def set_market_brief_and_note(brief_text: str, sentinel_note: str = "") -> None:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            UPDATE market_hud_snapshot SET
                brief_text = ?,
                last_sentinel_note = ?,
                updated_at = datetime('now')
            WHERE id = 1
            """,
            (brief_text or "", sentinel_note or ""),
        )
        conn.commit()
    finally:
        conn.close()


def get_market_brief_parts() -> Dict[str, str]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT brief_text, last_sentinel_note FROM market_hud_snapshot WHERE id = 1"
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


def get_market_hud_items() -> List[Dict[str, Any]]:
    """Compose HUD chips for /api/market/hud (watched symbols + prediction rows)."""
    items: List[Dict[str, Any]] = []
    for p in list_prediction_watch():
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
    for w in list_watched_symbols(active_only=True):
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


def format_market_snapshot_for_prompt() -> str:
    """Cached market / watchlist block for Chancellor (SQLite only)."""
    try:
        lines = ["[MARKET CACHE — temporary facts from ledger; verify via tools if live quote needed]"]
        ws = list_watched_symbols(active_only=True)
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
        pw = list_prediction_watch()
        if pw:
            lines.append("- Prediction watch (cached):")
            for p in pw[:16]:
                lines.append(
                    f"  • {p['slug']}: {p.get('label', '')} "
                    f"p={float(p.get('last_probability') or 0):.3f} trend={p.get('trend', '')}"
                )
        parts = get_market_brief_parts()
        if parts.get("last_sentinel_note"):
            lines.append(f"- Last sentinel note: {parts['last_sentinel_note']}")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("[FINANCE] market snapshot failed: %s", exc)
        return "[MARKET CACHE — unavailable]"


def get_last_n_days_spend(n: int = 7) -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT date, model_name, prompt_tokens, completion_tokens,
                   total_tokens, cost_usd, updated_at
            FROM api_usage_daily
            ORDER BY date DESC
            LIMIT ?
            """,
            (max(1, int(n)),),
        )
        return [dict(r) for r in c.fetchall()]
    finally:
        conn.close()


def format_ledger_snapshot() -> str:
    """Compact block for Chancellor prompt injection."""
    try:
        today = date.today()
        month_key = today.strftime("%Y-%m")
        bud = get_budget(month_key)
        exps = list_recurring_expenses(active_only=True)
        usage = get_last_n_days_spend(7)
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
]
