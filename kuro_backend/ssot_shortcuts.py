"""Kuro AI V6.0 Sovereign — SSoT shortcut router (P3.2) — bypass the LLM for high-confidence factual
queries whose answer lives entirely in SQLite (finances).

Rules:
- Only matches when the query is clearly factual AND phrased in a way the
  template formatter can answer faithfully (no "menurutmu", "analisis", etc.).
- Skipped entirely when persona is ``chill`` (needs generative tone).
- Skipped when the user references deictic anchors (``ini``, ``itu``,
  ``tadi``) so anaphora resolution still goes through the LLM.
- Output is plain Indonesian, no Markdown bullet soup — matches Kuro's casual
  tone without LLM spend.

The module is pure-Python + regex; all SQLite access goes through the
validated ``finance_db`` API, so SSoT guarantees are unchanged.

--- Header Doc ---
Purpose: Deterministic LLM-bypass router for high-confidence finance queries.
Caller: langgraph_core supervisor_node, main.py stream fastpath.
Dependencies: kuro_backend.finance_db, stdlib re + datetime.
Main Functions: try_shortcut(), is_shortcut_candidate().
Side Effects: None (read-only via finance_db accessors); log only.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Final, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------
# Query tokens that imply the user wants interpretation/analysis or personal
# opinion — these must always route to the LLM.
_OPINION_MARKERS: Final[tuple[str, ...]] = (
    "menurutmu", "menurut kamu", "menurut mu", "menurut lo", "menurut km",
    "analisis", "analisa", "analisislah",
    "evaluasi", "evaluasilah",
    "pendapat", "saranmu", "rekomendasi",
    "jelasin", "jelaskan", "kenapa",
    "bagaimana perasaan", "gimana kalau",
)

# Deictic anchors — skip shortcut, anaphora resolution needs LLM + referent grounding.
_DEICTIC_MARKERS: Final[tuple[str, ...]] = (
    " ini", " itu", " tadi", " barusan", " tersebut",
    "maksudnya", "gambar", "lampiran",
)


@dataclass(frozen=True)
class ShortcutResult:
    """Opaque wrapper so callers can cache or decorate the response."""
    response: str
    source: str  # e.g. "finances_budget", "finances_expenses"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
_DAY_NAMES_ID: Final[dict[int, str]] = {
    0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis",
    4: "Jumat", 5: "Sabtu", 6: "Minggu",
}

_MONTH_NAMES_ID: Final[dict[int, str]] = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
    9: "September", 10: "Oktober", 11: "November", 12: "Desember",
}


def _fmt_date_id(d: date) -> str:
    return f"{_DAY_NAMES_ID[d.weekday()]}, {d.day} {_MONTH_NAMES_ID[d.month]} {d.year}"


def _fmt_time_short(iso_ts: str) -> str:
    """Extract HH:MM from an ISO timestamp; return original on failure."""
    try:
        dt = datetime.fromisoformat(iso_ts)
        return dt.strftime("%H:%M")
    except Exception:
        return iso_ts


def _has_any(query: str, needles: Iterable[str]) -> bool:
    return any(n in query for n in needles)


# ---------------------------------------------------------------------------
# Pattern matchers — each returns a formatter or None
# ---------------------------------------------------------------------------

_BUDGET_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(what\s*(is|'s)\s*my\s*budget|my\s*budget|this\s*month'?s?\s*budget|"
    r"budget\s*remaining|monthly\s*budget|how\s*much\s*budget)\b",
    re.IGNORECASE,
)

_EXPENSES_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(recurring\s*expenses?|list\s*subscriptions?|monthly\s*bills?|"
    r"subscriptions?\s*list|what\s*subscriptions)\b",
    re.IGNORECASE,
)

_API_SPEND_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(api\s*spend|today'?s?\s*api\s*cost|api\s*usage|daily\s*api\s*cost|"
    r"api\s*cost\s*today)\b",
    re.IGNORECASE,
)


def _format_budget_row(row: Optional[dict], month_key: str) -> str:
    if not row:
        return (
            f"The ledger records no monthly_budget entry for {month_key}. "
            "Master may set one via the finances API or the Chancellor tools."
        )
    amt = float(row.get("amount_usd") or 0.0)
    notes = (row.get("notes") or "").strip()
    tail = f" Notes: {notes}" if notes else ""
    return f"Monthly budget ({month_key}): USD {amt:.2f}.{tail}"


def _format_recurring_expenses_block(rows: Sequence[dict]) -> str:
    if not rows:
        return "The ledger records no active recurring_expenses."
    lines = ["Active recurring obligations (from SSoT):"]
    for e in rows[:30]:
        lab = e.get("label") or "-"
        amt = float(e.get("amount_usd") or 0.0)
        cad = e.get("cadence") or "monthly"
        nxt = e.get("next_due") or ""
        lines.append(f"- {lab}: USD {amt:.2f} ({cad}), next due: {nxt or '—'}")
    return "\n".join(lines)


def _format_daily_api_spend(amount: float, date_str: str) -> str:
    return (
        f"Estimated API expenditure for {date_str} (api_usage_daily): "
        f"USD {amount:.4f}."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def try_shortcut(query: str, persona_mode: str) -> Optional[ShortcutResult]:
    """Return a :class:`ShortcutResult` if the query can be answered without the LLM.

    Returns ``None`` when no shortcut matches or when guardrails block the
    shortcut (opinion/deictic markers, ``chill`` persona).
    """
    if not query:
        return None

    # Import locally to avoid cycles during test discovery.
    from kuro_backend.services import core_service as core_data

    norm = " " + query.strip().lower() + " "
    persona = (persona_mode or "").strip().lower()

    if persona == "chill":
        return None
    if _has_any(norm, _OPINION_MARKERS):
        return None
    if _has_any(norm, _DEICTIC_MARKERS):
        return None

    try:
        if _BUDGET_PATTERN.search(norm):
            from kuro_backend import finance_db

            month_key = date.today().strftime("%Y-%m")
            row = finance_db.get_budget(month_key)
            return ShortcutResult(
                response=_format_budget_row(row, month_key),
                source="finances_budget",
            )

        if _EXPENSES_PATTERN.search(norm):
            from kuro_backend import finance_db

            rows = finance_db.list_recurring_expenses(active_only=True)
            return ShortcutResult(
                response=_format_recurring_expenses_block(rows),
                source="finances_expenses",
            )

        if _API_SPEND_PATTERN.search(norm):
            from kuro_backend import finance_db

            d = date.today().isoformat()
            cost = finance_db.get_daily_api_cost_usd(d)
            return ShortcutResult(
                response=_format_daily_api_spend(cost, d),
                source="finances_api_spend",
            )

        return None
    except Exception as exc:
        logger.warning("[SSOT_SHORTCUT] lookup failed, falling back to LLM: %s", exc)
        return None

    return None


__all__ = ["ShortcutResult", "try_shortcut"]
