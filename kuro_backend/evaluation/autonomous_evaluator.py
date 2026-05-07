from dataclasses import dataclass
import logging
from typing import List
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
        c.execute('''
            ALTER TABLE epistemic_log ADD COLUMN eval_groundedness REAL;
        ''')
        c.execute('''
            ALTER TABLE epistemic_log ADD COLUMN eval_goal_alignment REAL;
        ''')
        c.execute('''
            ALTER TABLE epistemic_log ADD COLUMN eval_epistemic REAL;
        ''')
        c.execute('''
            ALTER TABLE epistemic_log ADD COLUMN eval_composite REAL;
        ''')
        c.execute('''
            ALTER TABLE epistemic_log ADD COLUMN eval_rationale TEXT;
        ''')
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
