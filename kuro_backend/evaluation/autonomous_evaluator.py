"""
Kuro AI V1.0.0 Beta 3 "Sovereign Cat" - Evaluation Engine
================================================================================
Monitors reasoning quality via automated back-testing and epistemic auditing.

--- Header Doc ---
Purpose: Evaluates reasoning nodes for groundedness and goal alignment.
Caller: main.py (/api/evaluation/summary), background workers.
Dependencies: intelligence_db, dataset_builder.
Main Functions: run_evaluation_batch(), get_evaluation_summary().
Side Effects: Updates epistemic_log with eval scores.
"""
import logging
import sqlite3
from dataclasses import dataclass
from typing import List, Dict, Any
from .dataset_builder import EvalRecord, build_dataset

logger = logging.getLogger(__name__)

_EVAL_COLUMNS: dict[str, str] = {
    "eval_groundedness": "REAL",
    "eval_goal_alignment": "REAL",
    "eval_epistemic": "REAL",
    "eval_composite": "REAL",
    "eval_rationale": "TEXT",
}

@dataclass
class EvalScore:
    groundedness: float
    goal_alignment: float
    epistemic_compliance: float
    latency_risk: float
    composite: float
    rationale: str

def evaluate_record(record: EvalRecord) -> EvalScore:
    # Dummy mock scoring for now, production would call Gemini
    return EvalScore(1.0, 1.0, 1.0, 0.0, 1.0, "Mock evaluation")


def _empty_summary(reason: str = "No evaluation records have been written yet.") -> Dict[str, Any]:
    return {
        "status": "no_data",
        "message": reason,
        "metrics": {
            "groundedness": 0.0,
            "goal_alignment": 0.0,
            "epistemic_compliance": 0.0,
            "composite": 0.0,
        },
        "total_records": 0,
    }


def _intelligence_connection():
    """Return the intelligence DB connection used by the current runtime."""
    from kuro_backend import intelligence_db

    init_db = getattr(intelligence_db, "init_db", None)
    if callable(init_db):
        init_db()

    connection_factory = getattr(intelligence_db, "_get_connection", None)
    if not callable(connection_factory):
        connection_factory = getattr(intelligence_db, "_conn", None)
    if callable(connection_factory):
        return connection_factory()

    db_path = getattr(intelligence_db, "DB_PATH", None)
    if not db_path:
        raise RuntimeError("Intelligence DB path is not configured")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_eval_columns(cursor) -> bool:
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("epistemic_log",),
    )
    if cursor.fetchone() is None:
        return False

    cursor.execute("PRAGMA table_info(epistemic_log)")
    existing = {row["name"] if hasattr(row, "keys") else row[1] for row in cursor.fetchall()}
    for column, column_type in _EVAL_COLUMNS.items():
        if column not in existing:
            cursor.execute(f"ALTER TABLE epistemic_log ADD COLUMN {column} {column_type}")
    return True


def _round_metric(value: Any) -> float:
    if value is None:
        return 0.0
    return round(float(value), 3)

def run_evaluation_batch(since_hours: int = 24) -> List[EvalScore]:
    records = build_dataset(since_hours)
    scores = []
    conn = _intelligence_connection()
    try:
        c = conn.cursor()
        _ensure_eval_columns(c)
        conn.commit()
    except Exception:
        pass # Already exists

    for r in records:
        score = evaluate_record(r)
        scores.append(score)
        try:
            c = conn.cursor()
            c.execute('''
                UPDATE epistemic_log
                SET eval_groundedness = ?, eval_goal_alignment = ?, eval_epistemic = ?, eval_composite = ?, eval_rationale = ?
                WHERE source_query = ?
            ''', (score.groundedness, score.goal_alignment, score.epistemic_compliance, score.composite, score.rationale, r.input_text))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to persist eval score: {e}")
    conn.close()
    return scores

def get_evaluation_summary() -> Dict[str, Any]:
    """Retrieves aggregated evaluation metrics from the epistemic log."""
    conn = _intelligence_connection()
    try:
        c = conn.cursor()
        if not _ensure_eval_columns(c):
            return _empty_summary("Evaluation log table is not initialized yet.")
        conn.commit()
        c.execute('''
            SELECT 
                AVG(eval_groundedness) as avg_groundedness,
                AVG(eval_goal_alignment) as avg_alignment,
                AVG(eval_epistemic) as avg_epistemic,
                AVG(eval_composite) as avg_composite,
                COUNT(eval_composite) as total_evals
            FROM epistemic_log
            WHERE eval_composite IS NOT NULL
        ''')
        row = c.fetchone()
        if not row or row[4] == 0:
            return _empty_summary()
        
        return {
            "status": "success",
            "metrics": {
                "groundedness": _round_metric(row[0]),
                "goal_alignment": _round_metric(row[1]),
                "epistemic_compliance": _round_metric(row[2]),
                "composite": _round_metric(row[3]),
            },
            "total_records": row[4]
        }
    except Exception as e:
        logger.error(f"Failed to get evaluation summary: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()
