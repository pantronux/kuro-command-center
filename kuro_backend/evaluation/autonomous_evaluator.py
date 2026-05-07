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
from dataclasses import dataclass
import logging
from typing import List, Dict, Any
from .dataset_builder import EvalRecord, build_dataset

logger = logging.getLogger(__name__)

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

def run_evaluation_batch(since_hours: int = 24) -> List[EvalScore]:
    records = build_dataset(since_hours)
    scores = []
    from kuro_backend import intelligence_db
    conn = intelligence_db._conn()
    try:
        c = conn.cursor()
        c.execute('ALTER TABLE epistemic_log ADD COLUMN eval_groundedness REAL;')
        c.execute('ALTER TABLE epistemic_log ADD COLUMN eval_goal_alignment REAL;')
        c.execute('ALTER TABLE epistemic_log ADD COLUMN eval_epistemic REAL;')
        c.execute('ALTER TABLE epistemic_log ADD COLUMN eval_composite REAL;')
        c.execute('ALTER TABLE epistemic_log ADD COLUMN eval_rationale TEXT;')
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
    from kuro_backend import intelligence_db
    conn = intelligence_db._conn()
    try:
        c = conn.cursor()
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
            return {
                "status": "no_data",
                "metrics": {
                    "groundedness": 0.0,
                    "goal_alignment": 0.0,
                    "epistemic_compliance": 0.0,
                    "composite": 0.0,
                },
                "total_records": 0
            }
        
        return {
            "status": "success",
            "metrics": {
                "groundedness": round(row[0], 3),
                "goal_alignment": round(row[1], 3),
                "epistemic_compliance": round(row[2], 3),
                "composite": round(row[3], 3),
            },
            "total_records": row[4]
        }
    except Exception as e:
        logger.error(f"Failed to get evaluation summary: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()
