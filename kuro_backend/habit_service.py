"""
Grounded habit reporting: SQLite is the only source of habit facts for LLM narratives.

Used by habit_node (evaluasi) and response_node (konteks) to reduce hallucinated
activities, IPs, ISO clauses, etc.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from kuro_backend.services import core_service as core_data

logger = logging.getLogger(__name__)
logger.propagate = False

# System / grounding text for any Gemini call that narrates habits from structured data.
STRICT_HABIT_NARRATIVE_INSTRUCTION = (
    "Dilarang keras mengarang aktivitas, nomor IP, nomor klausul ISO, atau detail teknis "
    "jika tidak tercantum dalam data habit / habit_history yang disediakan. "
    "Jika data habit menunjukkan tidak ada penyelesaian (log selesai) dalam periode tersebut, "
    "katakan dengan jujur bahwa tidak ada catatan aktivitas habit yang tercatat di database. "
    "Utamakan kejujuran data daripada narasi yang terdengar profesional. "
    "Jangan mengklaim sumber 'Tier-1 Memory' atau 'sinkronisasi SQLite' kecuali kamu secara "
    "eksplisit merujuk pada blok data habit SQLite yang diberikan di pesan ini."
)

EMPTY_ACTIVITY_USER_LINE = (
    "Tidak ada catatan aktivitas habit (status selesai) dalam rentang waktu ini di database SQLite."
)


def fetch_sqlite_habit_snapshot(days: int = 30) -> Dict[str, Any]:
    """Pull habit definitions + logged completions (single writer: core_service)."""
    return core_data.fetch_habit_activity_snapshot(days)


def snapshot_has_no_positive_activity(snapshot: Dict[str, Any]) -> bool:
    """True if there is no recorded 'done' habit activity in the window (SQLite)."""
    if not snapshot.get("habits"):
        return True
    if snapshot.get("habit_log_done_count", 0) > 0:
        return False
    if snapshot.get("completion_history_count", 0) > 0:
        return False
    ts = snapshot.get("today_stats") or {}
    if int(ts.get("done") or 0) > 0:
        return False
    return True


def log_snapshot_debug(snapshot: Dict[str, Any], prefix: str = "[HABIT]") -> None:
    logger.info(
        "%s sqlite snapshot: habit_defs=%s today_done=%s/%s log_done_in_window=%s completion_rows_in_window=%s log_rows_fetched=%s",
        prefix,
        len(snapshot.get("habits") or []),
        (snapshot.get("today_stats") or {}).get("done"),
        (snapshot.get("today_stats") or {}).get("total"),
        snapshot.get("habit_log_done_count"),
        snapshot.get("completion_history_count"),
        len(snapshot.get("habit_log_rows") or []),
    )


def format_habit_block_for_llm(
    snapshot: Dict[str, Any],
    evaluation_text: str = "",
) -> str:
    """Single block for the model: facts + explicit empty rule."""
    lines: List[str] = [
        "[HABIT — HANYA GUNAKAN FAKTA SQLITE DI BAWAH INI]",
        STRICT_HABIT_NARRATIVE_INSTRUCTION,
        "",
        "RINGKASAN_SNAPSHOT:",
        json.dumps(
            {
                "today_completion_stats": snapshot.get("today_stats"),
                "habit_definitions": [
                    {
                        "title": h.get("title"),
                        "category": h.get("category"),
                        "is_done_today_flag": bool(h.get("is_done")),
                        "last_completed_date": h.get("last_completed_date"),
                    }
                    for h in (snapshot.get("habits") or [])
                ],
                "window_days": snapshot.get("window_days"),
                "completed_logs_in_window": snapshot.get("habit_log_done_count"),
                "completion_history_events_in_window": snapshot.get("completion_history_count"),
                "recent_habit_logs": (snapshot.get("habit_log_rows") or [])[:40],
                "recent_completion_dates": (snapshot.get("completion_samples") or [])[:20],
            },
            ensure_ascii=False,
            indent=2,
        ),
    ]
    if snapshot_has_no_positive_activity(snapshot):
        lines.extend(["", f"STATUS: {EMPTY_ACTIVITY_USER_LINE}"])

    if evaluation_text and evaluation_text.strip():
        lines.extend(["", "EVALUASI_AI_SEBELUMNYA (harus selaras dengan data di atas):", evaluation_text.strip()])

    return "\n".join(lines)


def build_monthly_eval_user_prompt(monthly_data: Dict[str, Any]) -> str:
    """User message body for monthly habit evaluation (system instruction is strict, separate)."""
    return f"""Kamu adalah Kuro, asisten dan mentor kedisiplinan yang sangat logis dan agak perfeksionis.
Evaluasi HANYA berdasarkan data habit bulan ini di bawah. Jangan menambahkan aktivitas, proyek, audit ISO, atau detail yang tidak muncul di data.

DATA HABIT BULAN INI (SQLite / aplikasi):
{json.dumps(monthly_data, indent=2, ensure_ascii=False)}

INSTRUKSI:
1. Jika tidak ada penyelesaian tercatat atau skor keseluruhan sangat rendah, nyatakan dengan jujur — jangan mengarang alasan "sibuk audit" dll.
2. Jika overall score atau ada habit di bawah 90%, tegur dengan tegas namun logis, hanya merujuk habit yang benar-benar ada di data.
3. Jika di atas 90%, berikan pujian singkat yang selaras data.
4. Format paragraf pendek, bahasa Indonesia. Tanpa nomor IP, tanpa klausul ISO, tanpa detail teknis yang tidak ada di data.

EVALUASI:"""
