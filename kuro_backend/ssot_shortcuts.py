"""Kuro AI V6.0 Sovereign — SSoT shortcut router (P3.2) — bypass the LLM for high-confidence factual
queries whose answer lives entirely in SQLite (habits / reminders).

Rules:
- Only matches when the query is clearly factual AND phrased in a way the
  template formatter can answer faithfully (no "menurutmu", "analisis", etc.).
- Skipped entirely when persona is ``chill`` (needs generative tone).
- Skipped when the user references deictic anchors (``ini``, ``itu``,
  ``tadi``) so anaphora resolution still goes through the LLM.
- Output is plain Indonesian, no Markdown bullet soup — matches Kuro's casual
  tone without LLM spend.

The module is pure-Python + regex; all SQLite access goes through the
validated ``core_service`` API, so SSoT guarantees are unchanged.

--- Header Doc ---
Purpose: Deterministic LLM-bypass router for high-confidence habit/reminder queries.
Caller: langgraph_core supervisor_node, main.py stream fastpath.
Dependencies: kuro_backend.services.core_service (habit + reminder getters), stdlib re + datetime.
Main Functions: match_shortcut(), format_habits_answer(), format_reminders_answer(), is_shortcut_candidate().
Side Effects: None (read-only via core_service accessors); log only.
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
    source: str  # e.g. "habits_today", "reminders_upcoming"


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
_HABIT_TODAY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(habit|habits?|kebiasaan)\b.*\b(hari\s*ini|udah\s*apa\s*aja|udah\s*selesai|selesai\s*apa)\b"
    r"|\bapa\s*aja\s*habit\b"
    r"|\bhabit\s*udah\s*apa\b",
    re.IGNORECASE,
)

_REMINDER_TODAY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(jadwal|reminder|pengingat|agenda)\b.*\b(hari\s*ini|today)\b"
    r"|\bhari\s*ini\s*(ada|apa)\s*jadwal\b",
    re.IGNORECASE,
)

_REMINDER_TOMORROW_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(jadwal|reminder|pengingat|agenda)\b.*\b(besok|tomorrow)\b"
    r"|\bbesok\s*(ada|apa)\s*jadwal\b",
    re.IGNORECASE,
)

_REMINDER_UPCOMING_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(jadwal|reminder|pengingat|agenda).*(mendatang|upcoming|berikutnya|selanjutnya|minggu\s*ini|minggu\s*depan)\b",
    re.IGNORECASE,
)

_HABIT_STREAK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(streak|kelanjutan)\b",
    re.IGNORECASE,
)

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


# ---------------------------------------------------------------------------
# Formatters (work entirely on SSoT data)
# ---------------------------------------------------------------------------
def _format_habits_today(habits: Sequence[dict]) -> str:
    if not habits:
        return "Belum ada habit tercatat di SSoT hari ini."
    today_iso = date.today().isoformat()
    done = [h for h in habits if h.get("completed_today")]
    pending = [h for h in habits if not h.get("completed_today")]

    lines: List[str] = [f"Status habit hari ini ({_fmt_date_id(date.today())}):"]
    if done:
        lines.append("Sudah selesai:")
        for h in done:
            name = h.get("name") or "-"
            streak = h.get("current_streak") or 0
            lines.append(f"- {name} (streak {streak} hari)")
    if pending:
        lines.append("Belum selesai:")
        for h in pending:
            name = h.get("name") or "-"
            lines.append(f"- {name}")
    lines.append(f"Ringkasan: {len(done)}/{len(habits)} habit selesai.")
    _ = today_iso  # reserved for future per-day filtering
    return "\n".join(lines)


def _format_habit_streaks(habits: Sequence[dict]) -> str:
    if not habits:
        return "Belum ada habit tercatat di SSoT."
    sorted_by_streak = sorted(habits, key=lambda h: int(h.get("current_streak") or 0), reverse=True)
    lines = ["Streak habit Master saat ini:"]
    for h in sorted_by_streak:
        name = h.get("name") or "-"
        cur = int(h.get("current_streak") or 0)
        best = int(h.get("best_streak") or 0)
        lines.append(f"- {name}: {cur} hari (terbaik {best} hari)")
    return "\n".join(lines)


def _format_reminders_for_date(reminders: Sequence[dict], target_day: date, label: str) -> str:
    same_day = [
        r for r in reminders
        if (r.get("datetime") or "").startswith(target_day.isoformat())
    ]
    if not same_day:
        return f"Tidak ada reminder tercatat di SSoT untuk {label} ({_fmt_date_id(target_day)})."
    same_day.sort(key=lambda r: r.get("datetime", ""))
    lines = [f"Reminder {label} ({_fmt_date_id(target_day)}):"]
    for r in same_day:
        when = _fmt_time_short(r.get("datetime", ""))
        desc = (r.get("description") or r.get("title") or "-").strip()
        lines.append(f"- {when} — {desc}")
    return "\n".join(lines)


def _format_reminders_upcoming(reminders: Sequence[dict]) -> str:
    if not reminders:
        return "Tidak ada reminder mendatang tercatat di SSoT."
    reminders = sorted(reminders, key=lambda r: r.get("datetime", ""))[:10]
    lines = ["Reminder mendatang (maks. 10, dari SSoT):"]
    for r in reminders:
        dt_iso = r.get("datetime", "")
        try:
            dt = datetime.fromisoformat(dt_iso)
            when = f"{_fmt_date_id(dt.date())} {dt.strftime('%H:%M')}"
        except Exception:
            when = dt_iso
        desc = (r.get("description") or r.get("title") or "-").strip()
        lines.append(f"- {when} — {desc}")
    return "\n".join(lines)


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

        if _HABIT_STREAK_PATTERN.search(norm):
            habits = core_data.list_habits_validated()
            return ShortcutResult(response=_format_habit_streaks(habits), source="habits_streaks")

        if _HABIT_TODAY_PATTERN.search(norm):
            habits = core_data.list_habits_validated()
            return ShortcutResult(response=_format_habits_today(habits), source="habits_today")

        if _REMINDER_TODAY_PATTERN.search(norm):
            reminders = core_data.list_reminders_upcoming_validated(limit=50)
            return ShortcutResult(
                response=_format_reminders_for_date(reminders, date.today(), "hari ini"),
                source="reminders_today",
            )

        if _REMINDER_TOMORROW_PATTERN.search(norm):
            reminders = core_data.list_reminders_upcoming_validated(limit=50)
            return ShortcutResult(
                response=_format_reminders_for_date(reminders, date.today() + timedelta(days=1), "besok"),
                source="reminders_tomorrow",
            )

        if _REMINDER_UPCOMING_PATTERN.search(norm):
            reminders = core_data.list_reminders_upcoming_validated(limit=20)
            return ShortcutResult(
                response=_format_reminders_upcoming(reminders),
                source="reminders_upcoming",
            )
    except Exception as exc:
        logger.warning("[SSOT_SHORTCUT] lookup failed, falling back to LLM: %s", exc)
        return None

    return None


__all__ = ["ShortcutResult", "try_shortcut"]
